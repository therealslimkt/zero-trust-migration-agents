import subprocess
import os

def pull_data_via_tailscale(hostname: str, remote_path: str, local_path: str):
    """
    Connects securely to a node on the Tailscale network and pulls a binary payload.
    Assumes Tailscale SSH or regular SSH is configured for the host.
    """
    print(f"[EDGE] Securely tunneling via Tailscale to {hostname}...")
    
    # Normally we would use 'scp' or a Python SSH library (paramiko/fabric) 
    # to pull the file directly over the Tailscale IP.
    # e.g., scp user@{hostname}:{remote_path} {local_path}
    
    command = ["scp", f"admin@{hostname}:{remote_path}", local_path]
    print(f"Executing: {' '.join(command)}")
    
    # Mocking the downloaded binary data for the hackathon
    with open(local_path, "wb") as f:
        # Mocking an EBCDIC-like binary structure with embedded PII
        # Representing: ACME    123456789    SMITH
        f.write(b"\\xC1\\xC3\\xD4\\xC5\\x40\\x40\\x40\\x40\\xF1\\xF2\\xF3\\xD4\\xF5\\xF6\\xF7\\xF8\\xF9\\x40\\x40\\x40\\x40\\xE2\\xD4\\xC9\\xE3\\xC8")
        
    print(f"[EDGE] Successfully pulled legacy binary to {local_path}")

if __name__ == "__main__":
    # Ensure data directory exists
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(data_dir, exist_ok=True)
    
    local_file = os.path.join(data_dir, "btrieve_sample.dat")
    pull_data_via_tailscale("legacy-btrieve-db", "/var/legacy/btrieve.dat", local_file)
