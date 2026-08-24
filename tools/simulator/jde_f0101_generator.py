import binascii
import os

def to_comp3(num, byte_length):
    """
    Convert an integer to a COBOL COMP-3 (Packed Decimal) byte string.
    JDE numeric types often use this on AS/400.
    """
    s = str(abs(num))
    # Packed decimal ends with a sign nibble: 'C' for positive, 'D' for negative
    sign = 'C' if num >= 0 else 'D'
    s += sign
    
    # Pad with leading zeros so it fits exactly into byte_length
    while len(s) < byte_length * 2:
        s = '0' + s
        
    return binascii.unhexlify(s)

def generate_f0101_record(an8, alph, tax):
    """
    Generate a single JDE F0101 (Address Book) binary record.
    Uses EBCDIC encoding for strings, COMP-3 for numbers.
    """
    # ABAN8 (Address Number) - Packed Decimal (5 bytes allows up to 9 digits)
    aban8_bytes = to_comp3(an8, 5)
    
    # ABALPH (Alpha Name) - EBCDIC String (40 chars)
    alph_ebcdic = alph.ljust(40).encode('cp037')
    
    # ABTAX (Tax ID) - EBCDIC String (20 chars)
    # E.g., SSN or EIN. This is the PII we want Gemma to redact!
    tax_ebcdic = tax.ljust(20).encode('cp037')
    
    return aban8_bytes + alph_ebcdic + tax_ebcdic

def main():
    # Ensure data directory exists
    data_dir = os.path.join(os.path.dirname(__file__), '../../data')
    os.makedirs(data_dir, exist_ok=True)
    
    filename = os.path.join(data_dir, 'F0101_address_book.bin')
    
    # Mock JDE Database Records (Notice the PII!)
    records = [
        (1001, "Acme Corporation", "12-3456789"),
        (1002, "Wayne Enterprises", "98-7654321"),
        (1003, "Bruce Wayne (Personal)", "SSN: 000-11-2222"), # Highly sensitive PII
        (1004, "Clark Kent", "SSN: 999-88-7777")            # Highly sensitive PII
    ]
    
    with open(filename, 'wb') as f:
        for r in records:
            f.write(generate_f0101_record(*r))
            
    print(f"✅ Generated authentic AS/400 EBCDIC binary dump at: {filename}")
    print("This file contains EBCDIC strings and COMP-3 packed decimals.")

if __name__ == "__main__":
    main()
