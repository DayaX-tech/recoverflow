"""
RecoverFlow — Customer notification channel

Demo build: wa.me deep link (zero-dependency, always works).
Production path: WhatsApp Business Cloud API / Twilio Content API —
both consume this same send_recovery_message() interface (pluggable transport).

The returned dict is written to the audit trail: every outbound
customer message is part of the evidence chain.
"""
import webbrowser
import urllib.parse


def send_recovery_message(customer_number: str, amount: str,
                          payment_link: str, retry_time: str) -> dict:
    """Compose the recovery message and open it in WhatsApp for dispatch."""
    msg = (
        f"Hi! Your PulseFit payment of {amount} failed. "
        f"Pay securely here: {payment_link} "
        f"(auto-retry scheduled for {retry_time}). "
        f"Reply to this message if you need help."
    )
    url = f"https://wa.me/{customer_number}?text={urllib.parse.quote(msg)}"
    webbrowser.open(url)
    return {
        "channel": "whatsapp",
        "method": "wa_me_deep_link",
        "to": customer_number,
        "message": msg,
        "status": "presented_for_dispatch",
    }


if __name__ == "__main__":
    result = send_recovery_message(
        customer_number="917989342710",          # your number for the test
        amount="₹1,499",
        payment_link="https://rzp.io/i/demo-test-link",
        retry_time="tomorrow 10 AM",
    )
    print("Message composed and opened in WhatsApp ✅")
    print("Audit record:", result)
