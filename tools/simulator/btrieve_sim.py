import struct
import os

def generate_btrieve_dummy(filepath):
    # Page size for our dummy Btrieve file (typical sizes are 512, 1024, 4096)
    PAGE_SIZE = 4096
    
    # 1. Create a 4096 byte FCB (File Control Block) - Page 0
    # In a real Btrieve file, this contains usage counts, file flags, and index specs.
    fcb_page = bytearray(PAGE_SIZE)
    # Pack a dummy signature 'FCB ' and the page size into the start of the file
    struct.pack_into('<4sH', fcb_page, 0, b'FCB ', PAGE_SIZE)
    
    # 2. Create a Data Page - Page 1
    # Page header: Page pointer (4 bytes, FFFFFFFF means end of list), Page Type (1 byte, 0x00 for data)
    data_page = bytearray(PAGE_SIZE)
    struct.pack_into('<IB', data_page, 0, 0xFFFFFFFF, 0x00)
    
    # 3. Inject a raw C-struct-like dummy record (no schema provided!)
    # Let's say the record is 64 bytes long:
    # Struct layout (hypothetical): [Record Length (2 bytes)] [String Data (40 bytes)] [Balance (Float, 4 bytes)]
    record_string = b'SAGE_ACCPAC_CUSTOMER_01'.ljust(40, b'\0')
    balance = 1530.50
    record_len = 2 + 40 + 4
    
    # Pack: Length (H), String (40s), Float (f)
    struct.pack_into('<H40sf', data_page, 5, record_len, record_string, balance)
    
    # Write the binary blocks to the file
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'wb') as f:
        f.write(fcb_page)
        f.write(data_page)
    
    print(f"[CARTRIDGE GENERATOR] Dummy Btrieve raw file generated at: {filepath}")
    print("[CARTRIDGE GENERATOR] Schema is hidden. Raw bytes must be interpreted externally to read 'SAGE_ACCPAC_CUSTOMER_01'.")

if __name__ == '__main__':
    target_path = os.path.join(os.path.dirname(__file__), 'dummy_accpac.mkd')
    generate_btrieve_dummy(target_path)
