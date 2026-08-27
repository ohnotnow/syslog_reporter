import smtplib
from email.message import EmailMessage
import dotenv
import os

dotenv.load_dotenv()

class EmailAgent:
    def __init__(self, body_text: str, attachment_text: str | None = None,
                 attachment_filename: str = "email_attachment.md",
                 recipients: str | None = None, subject: str = 'Syslog Report'):
        if recipients:
            self.recipients = recipients
        else:
            self.recipients = os.getenv("SYSLOG_SMTP_RECIPIENTS")

        if not self.recipients:
            raise ValueError("No recipients specified for email agent")

        self.body_text = body_text
        self.attachment_text = attachment_text
        self.attachment_filename = attachment_filename
        self.subject = subject
        self.smtp_server = os.getenv("SYSLOG_SMTP_SERVER")
        self.sender = os.getenv("SYSLOG_SMTP_SENDER")

    def build_message(self) -> EmailMessage:
        """Assemble the email: short digest as the body, full report attached."""
        msg = EmailMessage()
        msg.set_content(self.body_text)
        msg['Subject'] = self.subject
        msg['From'] = self.sender
        msg['To'] = self.sender  # Appears in the "To" field (BCC carries recipients)
        msg['Bcc'] = self.recipients
        if self.attachment_text:
            msg.add_attachment(
                self.attachment_text.encode('utf-8'),
                maintype='text', subtype='markdown',
                filename=self.attachment_filename,
            )
        return msg

    def run(self):
        """Sends the digest (with the full report attached) to recipients as BCC."""
        msg = self.build_message()
        try:
            with smtplib.SMTP(self.smtp_server) as server:
                server.send_message(msg)
                print(f"Email sent to {self.recipients}")
        except Exception as e:
            print(f"Failed to send email: {e}")
