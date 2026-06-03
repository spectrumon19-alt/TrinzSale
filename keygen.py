#!/usr/bin/env python3
"""
License Key Generator for TrintzPOS
Generates secure license keys with expiry dates and optional hardware binding.
"""

import os
import sys
import json
import csv
import hashlib
import secrets
import argparse
import platform
import getpass
from datetime import datetime, timedelta
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

class LicenseKeyGenerator:
    def __init__(self, master_key=None):
        """
        Initialize the license key generator.
        
        Args:
            master_key (bytes): Master key for encryption. If None, generates a new one.
        """
        if master_key is None:
            # Generate a new master key
            self.master_key = Fernet.generate_key()
        else:
            self.master_key = master_key
            
        self.cipher_suite = Fernet(self.master_key)
    
    def get_machine_id(self):
        """
        Generate a machine identifier based on system properties.
        This is used for hardware binding.
        """
        # Get system information
        system_info = f"{platform.system()}{platform.machine()}{platform.processor()}"
        
        # On Windows, we can get more specific info
        if platform.system() == "Windows":
            try:
                # Get volume serial number
                import subprocess
                result = subprocess.run(
                    ["cmd", "/c", "vol", "C:"], 
                    capture_output=True, text=True, check=True
                )
                if "Volume Serial Number" in result.stdout:
                    serial = result.stdout.split("Volume Serial Number")[-1].strip()
                    system_info += serial
            except:
                pass
        
        # On Unix-like systems, get MAC address
        else:
            try:
                import uuid
                mac = ':'.join(['{:02x}'.format((uuid.getnode() >> elements) & 0xff) 
                               for elements in range(0,2*6,2)][::-1])
                system_info += mac
            except:
                pass
        
        # Create a hash of the system info
        return hashlib.sha256(system_info.encode()).hexdigest()[:16]
    
    def generate_license_key(self, expiry_days=30, hardware_binding=False, license_type="Standard"):
        """
        Generate a license key with specified parameters.
        
        Args:
            expiry_days (int): Number of days until expiration (default: 30)
            hardware_binding (bool): Whether to bind to hardware (default: False)
            license_type (str): Type of license (Trial/Standard/Premium)
            
        Returns:
            dict: License key information
        """
        # Generate a unique license ID
        license_id = secrets.token_urlsafe(16)
        
        # Calculate expiry date
        creation_date = datetime.now()
        expiry_date = creation_date + timedelta(days=expiry_days)
        
        # Get machine ID if hardware binding is enabled
        machine_id = self.get_machine_id() if hardware_binding else None
        
        # Create license data
        license_data = {
            "license_id": license_id,
            "creation_date": creation_date.isoformat(),
            "expiry_date": expiry_date.isoformat(),
            "license_type": license_type,
            "hardware_binding": hardware_binding,
            "machine_id": machine_id,
            "activated": False,
            "activation_date": None
        }
        
        # Serialize and encrypt the license data
        serialized_data = json.dumps(license_data)
        encrypted_data = self.cipher_suite.encrypt(serialized_data.encode())
        
        # Create the final license key (base64 encoded for easy storage)
        license_key = base64.urlsafe_b64encode(encrypted_data).decode()
        
        # Add the license key to the data for return
        license_data["license_key"] = license_key
        
        return license_data
    
    def validate_license_key(self, license_key):
        """
        Validate a license key.
        
        Args:
            license_key (str): The license key to validate
            
        Returns:
            dict: License data if valid, None if invalid
        """
        try:
            # Decode and decrypt the license key
            encrypted_data = base64.urlsafe_b64decode(license_key.encode())
            decrypted_data = self.cipher_suite.decrypt(encrypted_data)
            license_data = json.loads(decrypted_data.decode())
            
            # Check if expired
            expiry_date = datetime.fromisoformat(license_data["expiry_date"])
            if datetime.now() > expiry_date:
                return None  # Expired license
            
            return license_data
        except:
            return None  # Invalid license key
    
    def activate_license(self, license_key, machine_id=None):
        """
        Activate a license key on a machine.
        
        Args:
            license_key (str): The license key to activate
            machine_id (str): Machine ID for validation (if hardware binding)
            
        Returns:
            dict: Updated license data if activation successful, None if failed
        """
        # Validate the license key first
        license_data = self.validate_license_key(license_key)
        if not license_data:
            return None
            
        # Check if already activated
        if license_data["activated"]:
            # If hardware binding is enabled, check if it's the same machine
            if (license_data["hardware_binding"] and 
                machine_id and 
                license_data["machine_id"] != machine_id):
                return None  # License activated on different machine
                
            return license_data  # Already activated on this machine
        
        # If hardware binding is required, verify machine ID
        if license_data["hardware_binding"]:
            if not machine_id:
                machine_id = self.get_machine_id()
                
            if license_data["machine_id"] != machine_id:
                return None  # Wrong machine
                
        # Activate the license
        license_data["activated"] = True
        license_data["activation_date"] = datetime.now().isoformat()
        
        # Re-encrypt the updated license data
        serialized_data = json.dumps(license_data)
        encrypted_data = self.cipher_suite.encrypt(serialized_data.encode())
        license_data["license_key"] = base64.urlsafe_b64encode(encrypted_data).decode()
        
        return license_data
    
    def save_master_key(self, filepath):
        """
        Save the master key to a file.
        
        Args:
            filepath (str): Path to save the master key
        """
        with open(filepath, 'wb') as f:
            f.write(self.master_key)
    
    def load_master_key(self, filepath):
        """
        Load the master key from a file.
        
        Args:
            filepath (str): Path to load the master key from
        """
        with open(filepath, 'rb') as f:
            self.master_key = f.read()
            self.cipher_suite = Fernet(self.master_key)
    
    def export_licenses_json(self, licenses, filepath):
        """
        Export licenses to a JSON file.
        
        Args:
            licenses (list): List of license data
            filepath (str): Path to export to
        """
        # Remove the actual license keys for security when exporting
        export_data = []
        for license_data in licenses:
            export_item = license_data.copy()
            # Don't export the actual license key for security
            export_item.pop("license_key", None)
            export_data.append(export_item)
        
        with open(filepath, 'w') as f:
            json.dump(export_data, f, indent=2)
    
    def export_licenses_csv(self, licenses, filepath):
        """
        Export licenses to a CSV file.
        
        Args:
            licenses (list): List of license data
            filepath (str): Path to export to
        """
        # Prepare data for CSV export
        export_data = []
        for license_data in licenses:
            export_item = {
                "license_id": license_data.get("license_id", ""),
                "creation_date": license_data.get("creation_date", ""),
                "expiry_date": license_data.get("expiry_date", ""),
                "license_type": license_data.get("license_type", ""),
                "hardware_binding": license_data.get("hardware_binding", False),
                "activated": license_data.get("activated", False),
                "activation_date": license_data.get("activation_date", "")
            }
            export_data.append(export_item)
        
        # Write to CSV
        with open(filepath, 'w', newline='') as f:
            if export_data:
                writer = csv.DictWriter(f, fieldnames=export_data[0].keys())
                writer.writeheader()
                writer.writerows(export_data)

def main():
    parser = argparse.ArgumentParser(description="TrintzPOS License Key Generator")
    parser.add_argument("--generate", action="store_true", help="Generate a new license key")
    parser.add_argument("--count", type=int, default=1, help="Number of licenses to generate")
    parser.add_argument("--days", type=int, default=30, help="License expiry in days")
    parser.add_argument("--type", choices=["Trial", "Standard", "Premium"], default="Standard", help="License type")
    parser.add_argument("--hardware", action="store_true", help="Enable hardware binding")
    parser.add_argument("--master-key", help="Path to master key file")
    parser.add_argument("--export-json", help="Export licenses to JSON file")
    parser.add_argument("--export-csv", help="Export licenses to CSV file")
    
    args = parser.parse_args()
    
    # Load or create master key
    generator = LicenseKeyGenerator()
    if args.master_key and os.path.exists(args.master_key):
        try:
            generator.load_master_key(args.master_key)
            print(f"Loaded master key from {args.master_key}")
        except Exception as e:
            print(f"Error loading master key: {e}")
            return
    elif args.master_key:
        # Save the newly generated master key
        generator.save_master_key(args.master_key)
        print(f"Generated and saved new master key to {args.master_key}")
    
    if args.generate:
        licenses = []
        print(f"Generating {args.count} license(s)...")
        print(f"License Type: {args.type}")
        print(f"Expiry Days: {args.days}")
        print(f"Hardware Binding: {'Yes' if args.hardware else 'No'}")
        print("-" * 50)
        
        for i in range(args.count):
            license_data = generator.generate_license_key(
                expiry_days=args.days,
                hardware_binding=args.hardware,
                license_type=args.type
            )
            licenses.append(license_data)
            
            print(f"License {i+1}:")
            print(f"  ID: {license_data['license_id']}")
            print(f"  Key: {license_data['license_key'][:20]}...")
            print(f"  Expiry: {license_data['expiry_date']}")
            print(f"  Type: {license_data['license_type']}")
            print()
        
        # Export if requested
        if args.export_json:
            generator.export_licenses_json(licenses, args.export_json)
            print(f"Exported licenses to {args.export_json}")
            
        if args.export_csv:
            generator.export_licenses_csv(licenses, args.export_csv)
            print(f"Exported licenses to {args.export_csv}")
            
        # Save master key if not already saved
        if not args.master_key:
            master_key_file = "master.key"
            generator.save_master_key(master_key_file)
            print(f"Master key saved to {master_key_file}")
            print("IMPORTANT: Keep this file secure and backup it properly!")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()