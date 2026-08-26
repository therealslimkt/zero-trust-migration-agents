
import codecs

ebcdic_hex = b'\xc1\xc3\xd4\xc5'

# Decode the EBCDIC hex stream using the IBM-037 codepage
ascii_text = codecs.decode(ebcdic_hex, 'cp037')

print(f"EBCDIC Hex: {ebcdic_hex.hex().upper()}")
print(f"Decoded ASCII: {ascii_text}")
