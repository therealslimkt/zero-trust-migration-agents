import yaml
import os
import json

def load_seed_data(filepath):
    with open(filepath, 'r') as file:
        return yaml.safe_load(file)

def seed_as400(data):
    print("Seeding AS400 (JDE) mock with Julian dates...")
    print(json.dumps(data['jde_as400'], indent=2))
    # In a real scenario, this would write to Postgres/Mock

def seed_maxdb(data):
    print("Seeding MaxDB (SAP) mock...")
    print(json.dumps(data['sap_maxdb'], indent=2))
    # In a real scenario, this would write to MySQL/Mock

def seed_btrieve(data):
    print("Seeding Btrieve (Accpac) mock...")
    print(json.dumps(data['accpac_btrieve'], indent=2))
    # In a real scenario, this would write hex bytes to a file

if __name__ == "__main__":
    filepath = os.path.join(os.path.dirname(__file__), '../data/seed_data.yml')
    if os.path.exists(filepath):
        data = load_seed_data(filepath)
        seed_as400(data)
        seed_maxdb(data)
        seed_btrieve(data)
        print("Database seeding complete!")
    else:
        print(f"Seed file not found at {filepath}")
