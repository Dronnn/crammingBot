-- Initial schema for vocabulary trainer bot.

CREATE TABLE users (
    id BIGINT PRIMARY KEY,
    username VARCHAR(255),
    first_name VARCHAR(255),
    active_pair_id INTEGER,
    reminders_enabled BOOLEAN DEFAULT TRUE,
    timezone VARCHAR(50) DEFAULT 'Europe/Moscow',
    last_training_at TIMESTAMP,
    last_daily_reminder_date DATE,
    last_intraday_reminder_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE language_pairs (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    source_lang VARCHAR(2) NOT NULL,
    target_lang VARCHAR(2) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, source_lang, target_lang)
);

ALTER TABLE users
    ADD CONSTRAINT users_active_pair_fk
    FOREIGN KEY (active_pair_id) REFERENCES language_pairs(id) ON DELETE SET NULL;

CREATE TABLE vocabulary_sets (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    language_pair_id INTEGER REFERENCES language_pairs(id),
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, language_pair_id, name)
);

CREATE TABLE words (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    language_pair_id INTEGER REFERENCES language_pairs(id),
    vocabulary_set_id INTEGER REFERENCES vocabulary_sets(id),
    word VARCHAR(500) NOT NULL,
    translation VARCHAR(500) NOT NULL,
    synonyms JSONB DEFAULT '[]',
    part_of_speech VARCHAR(50),
    gender VARCHAR(10),
    declension JSONB,
    transcription VARCHAR(255),
    note TEXT,
    tts_word_file_id VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE examples (
    id SERIAL PRIMARY KEY,
    word_id INTEGER REFERENCES words(id) ON DELETE CASCADE,
    sentence TEXT NOT NULL,
    translation_ru TEXT,
    translation_de TEXT,
    translation_en TEXT,
    translation_hy TEXT,
    tts_file_id VARCHAR(255),
    sort_order INTEGER DEFAULT 0
);

CREATE TABLE cards (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    word_id INTEGER REFERENCES words(id) ON DELETE CASCADE,
    language_pair_id INTEGER REFERENCES language_pairs(id),
    direction VARCHAR(10) NOT NULL,
    srs_index INTEGER DEFAULT 0,
    next_review_at TIMESTAMP NOT NULL,
    correct_count INTEGER DEFAULT 0,
    incorrect_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(word_id, direction)
);

CREATE TABLE reviews (
    id SERIAL PRIMARY KEY,
    card_id INTEGER REFERENCES cards(id) ON DELETE CASCADE,
    user_id BIGINT REFERENCES users(id),
    answer TEXT NOT NULL,
    is_correct BOOLEAN NOT NULL,
    response_time_ms INTEGER,
    reviewed_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_cards_next_review
    ON cards(user_id, language_pair_id, next_review_at);
CREATE INDEX idx_cards_word
    ON cards(word_id);
CREATE INDEX idx_words_pair
    ON words(user_id, language_pair_id);
CREATE INDEX idx_reviews_card
    ON reviews(card_id);
