"""WhatsApp-first auth — magic links + OTP fallback.

Modules:
    tokens — stateless HMAC-signed magic / session tokens.
    otp    — single-use 6-digit codes stored hashed in ``auth_otps``.
"""
