CREATE TABLE IF NOT EXISTS word_full_snapshots (
    word_id INTEGER PRIMARY KEY REFERENCES words(id) ON DELETE CASCADE,
    payload JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
