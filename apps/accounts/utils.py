from django.core.signing import TimestampSigner

signer = TimestampSigner()

def generate_token(email):
    return signer.sign(email)

def verify_token(token, max_age=86400):
    return signer.unsign(token, max_age=max_age)
