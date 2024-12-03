import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

def create_message(sender_email: str = "", bcc_email: str = "", subject: str = "Syslog Report", body: str = "Enjoy!", attachment_path: str = "temp.md"):
    message = MIMEMultipart()
    message["From"] = sender_email
    message["Bcc"] = bcc_email
    message["Subject"] = subject

    message.attach(MIMEText(body, "plain"))

    attachment = open(attachment_path, "rb")
    part = MIMEBase("application", "octet-stream")
    part.set_payload((attachment).read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f"attachment; filename= {attachment_path.split('/')[-1]}")
    message.attach(part)

def send_email(sender_email: str = "", bcc_email: str = "", subject: str = "Syslog Report", body: str = "Enjoy!", attachment_path: str = "temp.md", smtp_server: str = "", smtp_port: int = 25):
    message = create_message(sender_email, bcc_email, subject, body, attachment_path)
    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.send_message(message)
