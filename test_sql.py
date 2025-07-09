import pyodbc

try:
    conn = pyodbc.connect(
        "DRIVER={ODBC Driver 18 for SQL Server};"
        "SERVER=localhost;"
        "DATABASE=FormulareBazaDate;"
        "Trusted_Connection=yes;"
        "Encrypt=no;"
    )
    print("✅ Conexiune reușită!")
except Exception as e:
    print("❌ Eroare la conexiune:", e)
