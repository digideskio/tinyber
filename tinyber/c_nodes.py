# -*- Mode: Python -*-

from tinyber import nodes
from tinyber.writer import Writer
import sys

def csafe (s):
    return s.replace ('-', '_')

def int_max_size_type ( max_size):
    if max_size is None:
        # unconstrained int type.
        return 'asn1int_t'
    elif max_size < 2**8:
        return 'uint8_t'
    elif max_size < 2**16:
        return 'uint16_t'
    elif max_size < 2**32:
        return 'uint32_t'
    elif max_size < 2**64:
        return 'uint64_t'
    else:
        raise NotImplementedError()

class c_base_type (nodes.c_base_type):

    def emit (self, out):
        type_name, min_size, max_size = self.attrs
        if type_name == 'OCTET STRING' or type_name == 'UTF8String':
            out.writelines ('struct {')
            with out.indent():
                out.writelines (
                    'uint8_t val[%s];' % (max_size,),
                    'int len;'
                    )
            out.write ('}', True)
        elif type_name == 'BOOLEAN':
            out.write ('asn1bool_t', True)
        elif type_name == 'INTEGER':
            out.write (int_max_size_type (max_size), True)
        elif type_name == 'NULL':
            pass
        else:
            import pdb; pdb.set_trace()

    def emit_decode (self, out, lval, src):
        type_name, min_size, max_size = self.attrs
        out.writelines (
            'TYB_CHECK (decode_TLV (&tlv, %s));' % (src,),
            'TYB_FAILIF (tlv.type != %s);' % (self.tag_map[type_name],),
        )
        if type_name == 'OCTET STRING' or type_name == 'UTF8String':
            out.writelines (
                'TYB_FAILIF(tlv.length > %d);' % (max_size,),
                'memcpy ((*%s).val, tlv.value, tlv.length);' % (lval,),
                '(*%s).len = tlv.length;' % (lval,),
                )
        elif type_name == 'INTEGER':
            with out.scope():
                out.writelines ('asn1int_t intval = decode_INTEGER (&tlv);',)
                if max_size is not None:
                    out.writelines ('TYB_FAILIF(intval > %s);' % (max_size,),)
                if min_size is not None:
                    out.writelines ('TYB_FAILIF(intval < %s);' % (min_size,),)
                out.writelines ('*(%s) = intval;' % (lval,))
        elif type_name == 'BOOLEAN':
            out.writelines ('*(%s) = decode_BOOLEAN (&tlv);' % (lval,),)
        elif type_name == 'NULL':
            pass
        else:
            import pdb; pdb.set_trace()            

    def emit_encode (self, out, dst, src):
        type_name, min_size, max_size = self.attrs
        if type_name == 'OCTET STRING' or type_name == 'UTF8String':
            out.writelines ('TYB_CHECK (encode_OCTET_STRING (%s, (%s)->val, (%s)->len));' % (dst, src, src))
        elif type_name == 'INTEGER':
            with out.scope():
                out.writelines (
                    'asn1int_t intval = *%s;' % (src,),
                    'TYB_CHECK (encode_INTEGER (%s, &intval));' % (dst,),
                )
        elif type_name == 'BOOLEAN':
            with out.scope():
                out.writelines (
                    'asn1bool_t boolval = *%s;' % (src,),
                    'TYB_CHECK (encode_BOOLEAN (%s, &boolval));' % (dst,),
                )
        elif type_name == 'NULL':
            out.writelines ('encode_NULL (%s)' % (dst,))
        else:
            import pdb; pdb.set_trace()

class c_sequence (nodes.c_sequence):

    def emit (self, out):
        name, slots = self.attrs
        types = self.subs
        out.writelines ('struct %s {' % (name,))
        with out.indent():
            for i in range (len (slots)):
                slot_name = csafe (slots[i])
                slot_type = types[i]
                slot_type.emit (out)
                out.write (' %s;' % (slot_name,))
                out.newline()
        out.write ('}')

    def emit_decode (self, out, lval, src):
        name, slots = self.attrs
        types = self.subs
        out.writelines (
            'TYB_CHECK (decode_TLV (&tlv, %s));' % (src,),
            'TYB_FAILIF (tlv.type != TAG_SEQUENCE);',
            '{'
        )
        with out.indent():
            out.writelines (
                'buf_t src0;',
                'init_ibuf (&src0, tlv.value, tlv.length);'
            )
            for i in range (len (slots)):
                out.writelines ('// slot %s' % (slots[i],))
                slot_type = types[i]
                slot_type.emit_decode (out, '&(%s->%s)' % (lval, csafe (slots[i])), '&src0')
            out.writelines ('TYB_FAILIF (src0.pos != src0.size);')
        out.writelines ('}')

    def emit_encode (self, out, dst, src):
        name, slots = self.attrs
        types = self.subs
        out.writelines ('{')
        with out.indent():
            out.writelines ('unsigned int mark = %s->pos;' % (dst,))
            for i in reversed (range (len (slots))):
                out.writelines ('// slot %s' % (slots[i],))
                slot_type = types[i]
                slot_type.emit_encode (out, dst, '&(%s->%s)' % (src, csafe (slots[i])))
            out.writelines ('TYB_CHECK (encode_TLV (%s, mark, TAG_SEQUENCE));' % (dst,))
        out.writelines ('}')

class c_sequence_of (nodes.c_sequence_of):

    def emit (self, out):
        min_size, max_size, = self.attrs
        [seq_type] = self.subs
        out.writelines ('struct {')
        with out.indent():
            seq_type.emit (out)
            out.write (' val[%s];' % (max_size,))
            out.newline()
            out.writelines ('int len;')
        out.write ('}', True)

    def emit_decode (self, out, lval, src):
        min_size, max_size, = self.attrs
        [seq_type] = self.subs
        out.writelines ('{')
        with out.indent():
            out.writelines (
                'buf_t src1;',
                'int i;',
                'TYB_CHECK (decode_TLV (&tlv, %s));' % (src,),
                'TYB_FAILIF (tlv.type != TAG_SEQUENCE);',
                'init_ibuf (&src1, tlv.value, tlv.length);',
                '(%s)->len = 0;' % (lval,),
                'for (i=0; (src1.pos < src1.size); i++) {',
            )
            with out.indent():
                out.writelines ('TYB_FAILIF (i >= %s);' % (max_size,),)
                seq_type.emit_decode (out, '%s.val[i]' % (lval,), '&src1')
                out.writelines ('(%s)->len = i + 1;' % (lval,))
            out.writelines ('}')
            if min_size:
                out.writelines ('TYB_FAILIF ((%s)->len < %d);' % (lval, min_size))
        out.writelines ('}')

    def emit_encode (self, out, dst, src):
        min_size, max_size, = self.attrs
        [seq_type] = self.subs
        out.writelines ('{')
        with out.indent():
            out.writelines (
                'int i;',
                'unsigned int mark = %s->pos;' % (dst,),
                'int alen = (%s)->len;' % (src,),
                'for (i=0; i < alen; i++) {',
            )
            with out.indent():
                out.writelines ('TYB_FAILIF (i >= %s);' % (max_size,),)
                seq_type.emit_encode (out, dst, '&((%s)->val[alen-(i+1)])' % (src,))
            out.writelines (
                '}',
                'TYB_CHECK (encode_TLV (%s, mark, TAG_SEQUENCE));' % (dst,)
            )
        out.writelines ('}')

class c_choice (nodes.c_choice):

    def emit (self, out):
        name, slots, tags = self.attrs
        out.writelines ('struct %s {' % (name,))
        with out.indent():
            out.writelines ('%s_PR present;' % (name,))
            out.writelines ('union %s_u {' % (name,))
            with out.indent():
                for i in range (len (slots)):
                    slot_name = csafe (slots[i])
                    type_name = self.subs[i].name()
                    out.writelines ('%s_t %s;' % (type_name, slot_name))
            out.writelines ('} choice;')
        out.write ('}')
        
    def emit_enum (self, out):
        name, slots, tags = self.attrs
        # first emit the enum for type_PR
        out.writelines ('typedef enum {')
        with out.indent():
            for i in range (len (slots)):
                out.writelines ('%s_PR_%s = %s,' % (name, csafe (slots[i]), tags[i]))
        out.writelines ('} %s_PR;' % (name,), '')
        
    def emit_decode (self, out, lval, src):
        name, slots, tags = self.attrs
        types = self.subs
        out.writelines ('{')
        with out.indent():
            out.writelines (
                'buf_t src0;',
                'TYB_CHECK (decode_TLV (&tlv, %s));' % (src,),
                'init_ibuf (&src0, tlv.value, tlv.length);',
                'switch (tlv.type) {',
                )
            with out.indent():
                for i in range (len (slots)):
                    type_name = types[i].name()
                    tag_name = csafe (slots[i])
                    out.writelines (
                        'case (%s | FLAG_APPLICATION | FLAG_STRUCTURED):' % (tags[i],),
                        '  %s->present = %s_PR_%s;' % (lval, name, tag_name),
                        '  TYB_CHECK (decode_%s (&(%s->choice.%s), &src0));' % (type_name, lval, tag_name),
                        '  break;',
                    )
                out.writelines (
                    'default:', '  return -1;', '  break;'
                )
            out.writelines ('}')
        out.writelines ('}')

    def emit_encode (self, out, dst, src):
        name, slots, tags = self.attrs
        types = self.subs
        out.writelines ('{')
        with out.indent():
            out.writelines (
                'unsigned int mark = %s->pos;' % (dst,),
                'switch (%s->present) {' % (src,),
            )
            with out.indent():
                for i in range (len (slots)):
                    type_name = types[i].name()
                    tag_name = csafe (slots[i])
                    out.writelines (
                        'case %s:' % (tags[i],),
                        '  TYB_CHECK (encode_%s (%s, &(%s->choice.%s)));' % (type_name, dst, src, tag_name),
                        '  break;',
                    )
                out.writelines (
                    'default:', '  return -1;', '  break;'
                )
            out.writelines (
                '}',
                'TYB_CHECK (encode_TLV (%s, mark, %s->present | FLAG_APPLICATION | FLAG_STRUCTURED));' % (dst, src),
            )
        out.writelines ('}')

class c_enumerated (nodes.c_enumerated):

    def emit (self, out):
        alts, = self.attrs
        out.write ('enum {\n')
        with out.indent():
            for name, val in alts:
                if val is not None:
                    out.writelines ('%s = %s,' % (name, val))
                else:
                    out.writelines ('%s,' % (name,))
        out.write ('}')

    def emit_decode (self, out, lval, src):
        alts, = self.attrs
        out.writelines ('{')
        with out.indent():
            out.writelines (
                'TYB_CHECK (decode_TLV (&tlv, %s));' % (src,),
                'TYB_FAILIF (tlv.type != TAG_ENUMERATED);',
            )
            with out.scope():
                out.writelines (
                    'asn1int_t intval = decode_INTEGER (&tlv);',
                    'switch (intval) {'
                )
                with out.indent():
                    for name, val in alts:
                        out.writelines ('case %s: break;' % (val,))
                    out.writelines ('default: return -1;')
                out.writelines ('}')
                out.writelines ('*%s = intval;' % (lval,))
        out.writelines ('}')

    def emit_encode (self, out, dst, src):
        alts, = self.attrs
        with out.scope():
            out.writelines (
                'asn1int_t intval = *%s;' % (src,),
                'TYB_CHECK (encode_ENUMERATED (%s, &intval));' % (dst,),
            )

class c_defined (nodes.c_defined):

    def emit (self, out):
        name, max_size = self.attrs
        out.write ('%s_t' % (name,), True)

    def emit_decode (self, out, lval, src):
        type_name, max_size = self.attrs
        out.writelines ('TYB_CHECK (decode_%s (%s, %s));' % (type_name, lval, src),)

    def emit_encode (self, out, dst, src):
        type_name, max_size = self.attrs
        out.writelines ('TYB_CHECK (encode_%s (%s, %s));' % (type_name, dst, src),)
        

class CBackend:

    def __init__ (self, walker, module_name, base_path):
        self.walker = walker
        self.module_name = module_name
        self.base_path = base_path

    def gen_decoder (self, type_name, type_decl, node):
        # generate a decoder for a type assignment.
        sig = 'int decode_%s (%s_t * dst, buf_t * src)' % (type_name, type_name)
        self.hout.writelines (sig + ';')
        self.cout.writelines (sig, '{')
        with self.cout.indent():
            self.cout.writelines (
                'asn1raw_t tlv;',
            )
            node.emit_decode (self.cout, 'dst', 'src')
            self.cout.writelines ('return 0;')
        self.cout.writelines ('}', '')
        
    def gen_encoder (self, type_name, type_decl, node):
        # generate an encoder for a type assignment
        sig = 'int encode_%s (buf_t * dst, const %s_t * src)' % (type_name, type_name)
        self.cout.writelines (sig, '{')
        self.hout.writelines (sig + ';')
        with self.cout.indent():
            node.emit_encode (self.cout, 'dst', 'src')
            self.cout.writelines ('return 0;')
        self.cout.writelines ('}', '')

    def gen_codec_funs (self, type_name, type_decl, node):
        self.gen_decoder (type_name, type_decl, node)
        self.gen_encoder (type_name, type_decl, node)

    def generate_code (self):
        self.hout = Writer (open (self.base_path + '.h', 'wb'))
        self.cout = Writer (open (self.base_path + '.c', 'wb'))
        self.hout.writelines (
            '',
            '// generated by %r' % sys.argv,
            '// *** do not edit ***',
            '',
            '#ifndef _%s_H_' % self.module_name.upper(),
            '#define _%s_H_' % self.module_name.upper(),
            '',
            '#include <stdint.h>',
            '#include <string.h>',
            '#include "tinyber.h"',
            '',
            '#define TYB_FAILIF(x) do { if (x) { return -1; } } while(0)',
            '#define TYB_CHECK(x) TYB_FAILIF(-1 == (x))',
            ''
        )
        self.cout.writelines (
            '',
            '// generated by %r' % sys.argv,
            '// *** do not edit ***',
            '',
            '#include "%s.h"' % (self.module_name,),
            '',
            # needed for the inline defs when compiled with inlining disabled.
            'extern void init_obuf (buf_t * self, uint8_t * buffer, unsigned int size);',
            'extern void init_ibuf (buf_t * self, uint8_t * buffer, unsigned int size);',
            '',
        )

        self.tag_assignments = self.walker.tag_assignments

        # generate typedefs and prototypes.
        out = self.hout
        for (type_name, node, type_decl) in self.walker.defined_types:
            if isinstance (node, c_choice):
                node.emit_enum (out)
            out.write ('typedef ')
            node.emit (out)
            out.writelines (
                ' %s_t;' % (type_name,),
                '#define %s_MAX_SIZE %d' % (type_name, node.max_size()),
                ''
            )

        for (type_name, node, type_decl) in self.walker.defined_types:
            self.gen_codec_funs (type_name, type_decl, node)

        self.hout.writelines (
            '',
            '#endif // _%s_H_' % self.module_name.upper()
        )
        self.hout.close()
        self.cout.close()