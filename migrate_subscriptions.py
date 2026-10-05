import sqlite3
import database

conn = sqlite3.connect(database.DB_PATH)
cols = [r[1] for r in conn.execute('PRAGMA table_info(customers)').fetchall()]

migrations = [
    ('subscription_status', "TEXT DEFAULT 'trial' CHECK (subscription_status IN ('trial','active','past_due','cancelled'))"),
    ('paystack_customer_id', 'TEXT'),
    ('paystack_subscription_id', 'TEXT'),
    ('subscription_expires_at', 'TEXT'),
    ('monthly_scan_limit', 'INTEGER DEFAULT 30'),
    ('monthly_tailor_limit', 'INTEGER DEFAULT 50'),
    ('monthly_email_limit', 'INTEGER DEFAULT 100'),
    ('daily_token_budget', 'INTEGER DEFAULT 50000'),
]

for col, ddl in migrations:
    if col not in cols:
        conn.execute(f'ALTER TABLE customers ADD COLUMN {col} {ddl}')
        print(f'Added {col}')
    else:
        print(f'Exists {col}')

conn.commit()
print('Migration done')