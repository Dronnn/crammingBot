CREATE TABLE IF NOT EXISTS reminder_quiz_states (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    direction VARCHAR(10) NOT NULL,
    source_lang VARCHAR(2) NOT NULL,
    target_lang VARCHAR(2) NOT NULL,
    word VARCHAR(500) NOT NULL,
    translation VARCHAR(500) NOT NULL,
    synonyms JSONB NOT NULL DEFAULT '[]',
    srs_index INTEGER NOT NULL,
    sent_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reminder_quiz_states_sent_at
    ON reminder_quiz_states(sent_at);
