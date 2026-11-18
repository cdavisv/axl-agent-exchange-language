import unittest
from native_tools import arguments_to_axl, axl_to_arguments, brief_instruction, tool_definition
from axl3 import Error, Schema, dump, pack, registry, unpack
bridge = arguments_to_axl
tool_schema = tool_definition

class BridgeTests(unittest.TestCase):

    def setUp(self):
        self.s = Schema('test', (('id', 'string', True), ('value', 'any', False)))

    def test_exact_types(self):
        records = [{'id': '001', 'value': None}, {'id': '1.0', 'value': 1.0}, {'id': 'true', 'value': False}, {'id': 'x'}]
        self.assertEqual(dump(unpack(bridge(dump({'records': records}), self.s), registry(self.s))), dump(records))

    def test_missing_and_extra(self):
        for x in ({}, {'records': [], 'x': 1}, {'records': [{'value': 1}]}, {'records': [{'id': 'x', 'extra': 1}]}):
            with self.assertRaises(Error):
                bridge(dump(x), self.s)

    def test_types(self):
        for x in (None, [], {'records': None}, {'records': {}}, {'records': [{'id': 1}]}):
            with self.assertRaises(Error):
                bridge(dump(x), self.s)

    def test_duplicate_and_nan(self):
        for x in ('{"records":[],"records":[]}', '{"records":[{"id":"x","value":NaN}]}'):
            with self.assertRaises(Error):
                bridge(x, self.s)

    def test_shared(self):
        r = [{'id': 'x', 'value': [1]}, {'id': 'x', 'value': [1]}]
        out = unpack(bridge(dump({'records': r}), self.s, ('value',)), registry(self.s))
        out[0]['value'].append(2)
        self.assertEqual(out[1]['value'], [1])

    def test_limits(self):
        with self.assertRaises(Error):
            bridge(dump({'records': [{'id': 'x'}] * 1025}), self.s)

    def test_tool_schema_optional(self):
        d = tool_schema(self.s)['function']['parameters']['properties']['records']['items']
        self.assertEqual(d['required'], ['id'])
        self.assertFalse(d['additionalProperties'])
        self.assertEqual(d['properties']['value'], {})

    def test_unicode(self):
        r = [{'id': '東京\n\t\\', 'value': {'text': 'é'}}]
        self.assertEqual(unpack(bridge(dump({'records': r}), self.s), registry(self.s)), r)

    def test_reverse(self):
        r = [{'id': '001', 'value': None}, {'id': '002'}]
        wire = bridge(dump({'records': r}), self.s)
        self.assertEqual(axl_to_arguments(wire, self.s), dump({'records': r}))
        other = Schema('other', self.s.fields)
        with self.assertRaises(Error):
            axl_to_arguments(wire, other)

    def test_brief_required(self):
        with self.assertRaises(Error):
            brief_instruction(self.s)
        s = Schema('required', (('id', 'string', True),))
        self.assertIn(dump(s.definition), brief_instruction(s))

    def test_fresh_schema_metadata(self):
        first = tool_definition(self.s)
        first['function']['parameters']['required'].append('bad')
        self.assertEqual(tool_definition(self.s)['function']['parameters']['required'], ['records'])

    def test_wrapper_boundary(self):
        schema = Schema('edge', (('x', 'string', True),))
        records = [{'x': 'a' * 131062}] * 2
        wire = pack(records, schema, ('x',))
        self.assertEqual(unpack(wire, registry(schema)), records)
        with self.assertRaises(Error):
            axl_to_arguments(wire, schema)

    def test_empty(self):
        self.assertEqual(axl_to_arguments(bridge('{"records":[]}', self.s), self.s), '{"records":[]}')
if __name__ == '__main__':
    unittest.main()
