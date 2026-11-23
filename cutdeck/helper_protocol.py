"""Where the helper listens and which protocol it speaks. Import-free, so a client that only
talks to the helper (cdv.py, ai_backend) starts without loading the helper or its commands."""

PORT = 7891
VERSION = "cutdeck-7"  # premiere_transcript: clip transcript JSON for Premiere
