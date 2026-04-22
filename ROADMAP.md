# Roadmap

## Phase 1 — Polish the basics
- Show audio duration on each card
- Volume slider per sound (or global)
- Keyboard shortcut to trigger sounds (assign a key per card)
- Reorder / pin favorite sounds to the top

## Phase 2 — Better admin
- Edit a sound's name/category after upload without deleting and re-adding
- Bulk delete
- Simple backup: one-click download of all sounds + `sounds_db.json` as a zip

## Phase 3 — Multi-user
- Multiple admin accounts with hashed passwords (swap JSON auth for a small SQLite users table)
- Read-only shareable link (current behaviour for non-admins is already this, but make it explicit)

## Phase 4 — Quality of life
- Waveform preview on the card (using Web Audio API — no extra deps)
- Mobile-friendly record button (current UI is desktop-first)
- Auto-trim silence from recordings before saving
