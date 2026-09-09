import os

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from utils_logger import SENDER, TERMIN_URL, logger


def get_email_addresses():
    email_txt = os.getenv("EMAIL_IDS").split(",")
    email_addresses = [email.strip() for email in email_txt if email.strip()]
    return email_addresses


def get_email_body(body):
    return f"""
    <!DOCTYPE html>
        <html lang="en">

        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>New Appointment Available</title>
        </head>

        <body style="
            margin: 0;
            padding: 0;
            background-color: #f4f6f8;
            font-family: Arial, Helvetica, sans-serif;
            color: #1f2937;
        ">

            <table width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation"
                style="background-color: #f4f6f8;">
                <tr>
                    <td align="center" style="padding: 40px 15px;">

                        <!-- Main container -->
                        <table width="600" border="0" cellpadding="0" cellspacing="0" role="presentation" style="
                                width: 100%;
                                max-width: 600px;
                                background-color: #ffffff;
                                border-radius: 12px;
                                overflow: hidden;
                            ">

                            <!-- Header -->
                            <tr>
                                <td align="center" style="
                                        padding: 32px 30px;
                                        background-color: #2563eb;
                                    ">
                                    <div style="
                                        font-size: 30px;
                                        line-height: 36px;
                                        margin-bottom: 8px;
                                    ">
                                        📅
                                    </div>

                                    <h1 style="
                                        margin: 0;
                                        color: #ffffff;
                                        font-size: 26px;
                                        line-height: 34px;
                                        font-weight: 700;
                                    ">
                                        New Appointment Available
                                    </h1>

                                    <p style="
                                        margin: 8px 0 0 0;
                                        color: #dbeafe;
                                        font-size: 15px;
                                        line-height: 22px;
                                    ">
                                        An appointment matching your alert is available.
                                    </p>
                                </td>
                            </tr>

                            <!-- Content -->
                            <tr>
                                <td style="padding: 35px 35px 30px 35px;">

                                    <p style="
                                        margin: 0 0 20px 0;
                                        font-size: 16px;
                                        line-height: 26px;
                                        color: #374151;
                                    ">
                                        Hello,
                                    </p>

                                    <p style="
                                        margin: 0 0 25px 0;
                                        font-size: 16px;
                                        line-height: 26px;
                                        color: #374151;
                                    ">
                                        A new appointment is now available. Here are the
                                        details:
                                    </p>

                                    <!-- Appointment details -->
                                    <table width="100%" border="0" cellpadding="0" cellspacing="0" role="presentation" style="
                                            background-color: #f8fafc;
                                            border: 1px solid #e5e7eb;
                                            border-radius: 8px;
                                        ">
                                        <tr>
                                            <td style="
                                                padding: 20px;
                                                font-size: 15px;
                                                line-height: 24px;
                                                color: #374151;
                                            ">
                                                {body}
                                            </td>
                                        </tr>
                                    </table>

                                    <p style="
                                        margin: 25px 0 0 0;
                                        font-size: 14px;
                                        line-height: 22px;
                                        color: #6b7280;
                                    ">
                                        Please check <a href="{TERMIN_URL}" style="color: #2563eb; text-decoration: underline;">the appointment details</a> and take
                                        action if it is suitable for you.
                                    </p>

                                </td>
                            </tr>

                            <!-- Footer -->
                            <tr>
                                <td style="
                                    padding: 22px 30px;
                                    background-color: #f8fafc;
                                    border-top: 1px solid #e5e7eb;
                                ">
                                    <p style="
                                        margin: 0;
                                        text-align: center;
                                        font-size: 12px;
                                        line-height: 18px;
                                        color: #9ca3af;
                                    ">
                                        Appointment Alert &bull; Automated notification
                                    </p>
                                </td>
                            </tr>

                        </table>

                    </td>
                </tr>
            </table>

        </body>

    </html>
    """

def send_ses_email(email, subject, body, from_tele=False):
    email_subject = subject or "New Appointment Available"
    BODY_HTML = body if from_tele else get_email_body(body)
    CHARSET = "UTF-8"

    access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
    secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    region_name = os.getenv("AWS_REGION")

    if not access_key_id or not secret_access_key or not region_name:
        logger.error(
            "Missing AWS credentials in .env. Set AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and AWS_REGION."
        )
        return False

    client = boto3.client(
        "ses",
        region_name=region_name,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
    )

    try:
        client.send_email(
            Destination={
                "ToAddresses": [email],
            },
            Message={
                "Body": {
                    "Html": {
                        "Charset": CHARSET,
                        "Data": BODY_HTML,
                    },
                    "Text": {
                        "Charset": CHARSET,
                        "Data": body,
                    },
                },
                "Subject": {
                    "Charset": CHARSET,
                    "Data": email_subject,
                },
            },
            Source=SENDER,
            ConfigurationSetName=os.getenv("AWS_SES_CONFIGURATION_SET")

        )
        return True
    except NoCredentialsError:
        logger.error("AWS SES credentials were not found in the .env file.")
        return False
    except ClientError as exc:
        logger.error("AWS SES request failed: %s", exc.response["Error"]["Message"])
        return False
    finally:
        if client:
            client.close()