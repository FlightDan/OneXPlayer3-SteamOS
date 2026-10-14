import unittest
from fs_metadata import parse_output, normalize_uuid


class FilesystemMetadataChecks(unittest.TestCase):
    def test_busybox_and_util_linux_default_fields(self):
        line = '/dev/vde: LABEL="OXP_INTENT" UUID="135b8493-e795-45fa-863e-5cc60a582df6" TYPE="ext4"\n'
        self.assertEqual(parse_output(line, '/dev/vde')['TYPE'], 'ext4')
        self.assertEqual(parse_output(line, '/dev/vde')['LABEL'], 'OXP_INTENT')
        self.assertEqual(normalize_uuid(line, '/dev/vde'), '135b8493-e795-45fa-863e-5cc60a582df6')

    def test_uuid_is_not_device_descriptor_or_label(self):
        value = '/dev/vdd3: LABEL="OXP3_STAGE" UUID="ABCD-1234" TYPE="vfat"'
        self.assertEqual(normalize_uuid(value, '/dev/vdd3'), 'abcd-1234')
        self.assertEqual(normalize_uuid('ABCD-1234'), 'abcd-1234')

    def test_multiple_lines_duplicate_fields_and_foreign_device_refused(self):
        for output in ('/dev/vde: TYPE="ext4"\n/dev/vdd: TYPE="ntfs"', '/dev/vde: TYPE="ext4" TYPE="ntfs"', '/dev/vdd: TYPE="ntfs"'):
            with self.assertRaises(RuntimeError): parse_output(output, '/dev/vde')

    def test_empty_signature_is_not_filesystem(self):
        self.assertEqual(parse_output(''), {})

    def test_malformed_or_missing_uuid_refused(self):
        for value in ('foreign', '/dev/vde: TYPE="ext4"', '/dev/vde: UUID="not-a-real-id"', None):
            with self.assertRaises(RuntimeError): normalize_uuid(value)

    def test_label_spaces_and_quotes_are_data(self):
        self.assertEqual(parse_output('/dev/vde: LABEL="a \\"quoted\\" label" TYPE="ext4"')['LABEL'], 'a "quoted" label')


if __name__ == '__main__': unittest.main(verbosity=2)
