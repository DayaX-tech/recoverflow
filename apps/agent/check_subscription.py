import sqlite3

conn = sqlite3.connect("pulsefit.db")

print("LATEST ORDERS:")
orders = conn.execute("""
    SELECT order_id, plan, phone, amount, status
    FROM orders
    ORDER BY id DESC
    LIMIT 5
""").fetchall()

for row in orders:
    print(row)

print("\nSUBSCRIPTIONS:")
subscriptions = conn.execute("""
    SELECT subscription_id, phone, plan, amount, status,
           started_at, next_billing_at, autopay_enabled
    FROM subscriptions
    ORDER BY id DESC
    LIMIT 5
""").fetchall()

for row in subscriptions:
    print(row)

conn.close()