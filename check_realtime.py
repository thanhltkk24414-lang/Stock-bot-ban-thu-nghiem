import sqlite3
conn = sqlite3.connect("data/market_data.db")
cursor = conn.execute(
    "SELECT symbol, data_type, timestamp FROM market_data "
    "WHERE symbol = 'HPG' ORDER BY timestamp DESC LIMIT 5;"
)
print(cursor.fetchall())
conn.close()