# proj8-Gcal
Snarf appointment data from a selection of a user's Google calendars 

## What you need
Google calendar api credentials json

## Usage
- Import your Google calendar api credentials json into /meetings
- Copy its file's name(usually client_id.json) and paste into app.ini's "GOOGLE_KEY_FILE" option.
- You can assign another port number by modifying it in the app.ini
- "make start"
-  Set date range and time range, and then you can see your free and busy times.
