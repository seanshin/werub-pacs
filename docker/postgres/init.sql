-- Create separate database for Keycloak
CREATE DATABASE keycloak;
GRANT ALL PRIVILEGES ON DATABASE keycloak TO openpacs;

-- Enable extensions for main database
\c openpacs;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
