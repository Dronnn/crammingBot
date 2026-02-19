DROP INDEX IF EXISTS idx_reviews_card;
DROP INDEX IF EXISTS idx_words_pair;
DROP INDEX IF EXISTS idx_cards_word;
DROP INDEX IF EXISTS idx_cards_next_review;

DROP TABLE IF EXISTS word_full_snapshots;
DROP TABLE IF EXISTS reviews;
DROP TABLE IF EXISTS cards;
DROP TABLE IF EXISTS examples;
DROP TABLE IF EXISTS words;
DROP TABLE IF EXISTS vocabulary_sets;

ALTER TABLE IF EXISTS users
    DROP CONSTRAINT IF EXISTS users_active_pair_fk;

DROP TABLE IF EXISTS language_pairs;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS schema_migrations;
