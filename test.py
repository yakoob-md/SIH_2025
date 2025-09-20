import os
from dotenv import load_dotenv
from urllib.parse import urlparse
import mysql.connector
import subprocess

# Load environment variables
load_dotenv()

def check_mysql_service():
    """Check if MySQL service is running"""
    try:
        result = subprocess.run(['sc', 'query', 'mysql'], capture_output=True, text=True)
        if 'RUNNING' in result.stdout:
            print("✅ MySQL service is RUNNING")
            return True
        else:
            print("❌ MySQL service is NOT RUNNING")
            print("Try running: net start mysql")
            return False
    except Exception as e:
        print(f"Could not check MySQL service status: {e}")
        return False

def test_direct_connection():
    """Test direct connection with known working credentials"""
    print("\n=== Testing Direct Connection ===")
    try:
        connection = mysql.connector.connect(
            host='localhost',
            user='root',
            password='Abhinav@2004',
            port=3306
        )
        if connection.is_connected():
            print("✅ Direct connection successful!")
            connection.close()
            return True
    except mysql.connector.Error as e:
        print(f"❌ Direct connection failed: {e}")
        return False

def parse_database_url(database_url):
    """Parse MySQL database URL and return connection config"""
    if not database_url:
        raise ValueError("DATABASE_URL is required")
    
    parsed = urlparse(database_url)
    print(f"Parsed URL components:")
    print(f"  scheme: {parsed.scheme}")
    print(f"  hostname: {parsed.hostname}")
    print(f"  port: {parsed.port}")
    print(f"  username: {parsed.username}")
    print(f"  password: {parsed.password}")
    print(f"  path: {parsed.path}")
    
    return {
        'host': parsed.hostname,
        'port': parsed.port or 3306,
        'user': parsed.username,
        'password': parsed.password,
        'database': parsed.path[1:] if parsed.path else None,
        'charset': 'utf8mb4',
        'collation': 'utf8mb4_unicode_ci',
        'autocommit': True
    }

def test_parsed_connection():
    """Test connection using parsed DATABASE_URL"""
    print("\n=== Testing Parsed DATABASE_URL ===")
    database_url = os.getenv('DATABASE_URL')
    print(f"DATABASE_URL: {database_url}")
    
    if not database_url:
        print("❌ DATABASE_URL not found in .env file!")
        return False
        
    try:
        config = parse_database_url(database_url)
        print(f"Parsed config: {config}")
        
        # Remove problematic keys that might cause issues
        clean_config = {
            'host': config['host'],
            'port': config['port'],
            'user': config['user'],
            'password': config['password']
        }
        
        connection = mysql.connector.connect(**clean_config)
        if connection.is_connected():
            print("✅ Parsed connection successful!")
            connection.close()
            return True
    except Exception as e:
        print(f"❌ Parsed connection failed: {e}")
        return False

if __name__ == "__main__":
    print("=== MySQL Connection Diagnostics ===")
    
    # Step 1: Check if MySQL service is running
    mysql_running = check_mysql_service()
    
    # Step 2: Test direct connection
    direct_works = test_direct_connection()
    
    # Step 3: Test parsed connection
    parsed_works = test_parsed_connection()
    
    print("\n=== Summary ===")
    print(f"MySQL Service Running: {'✅' if mysql_running else '❌'}")
    print(f"Direct Connection: {'✅' if direct_works else '❌'}")
    print(f"Parsed Connection: {'✅' if parsed_works else '❌'}")
    
    if not mysql_running:
        print("\n🔧 To fix: Run 'net start mysql' as administrator")
    elif direct_works and not parsed_works:
        print("\n🔧 Issue is with DATABASE_URL parsing - check the URL format")
    elif not direct_works:
        print("\n🔧 Issue is with MySQL credentials or configuration")