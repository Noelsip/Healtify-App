import logging
from typing import List, Optional, Dict, Any
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone
from .models import Dispute, Claim

logger = logging.getLogger(__name__)

class EmailNotificationService:
    """Service untuk mengirim email notifications."""
    
    def __init__(self):
        self.enabled = getattr(settings, 'ENABLE_EMAIL_NOTIFICATIONS', False)
        self.from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', '')
        self.from_name = getattr(settings, 'NOTIFICATION_FROM_NAME', 'Healthify')
        self.admin_emails = getattr(settings, 'ADMIN_NOTIFICATION_EMAILS', [])
    
    def _build_from_header(self) -> str:
        """Build email from header dengan format: Name <email>"""
        return f"{self.from_name} <{self.from_email}>"
    
    def _send_email(self, subject: str, message: str, recipient_list: List[str], 
                   html_message: Optional[str] = None) -> bool:
        """
        Internal method untuk mengirim email.
        
        Returns:
            bool: True jika berhasil, False jika gagal
        """
        if not self.enabled:
            logger.info(f"[EMAIL] Notifications disabled. Skipping email: {subject}")
            return False
        
        if not recipient_list:
            logger.warning(f"[EMAIL] No recipients for: {subject}")
            return False
        
        try:
            if html_message:
                email = EmailMultiAlternatives(
                    subject=subject,
                    body=message,
                    from_email=self._build_from_header(),
                    to=recipient_list
                )
                email.attach_alternative(html_message, "text/html")
                email.send()
            else:
                send_mail(
                    subject=subject,
                    message=message,
                    from_email=self._build_from_header(),
                    recipient_list=recipient_list,
                    fail_silently=False,
                )
            
            logger.info(f"[EMAIL] Sent to {', '.join(recipient_list)}: {subject}")
            return True
            
        except Exception as e:
            logger.error(f"[EMAIL] Failed to send '{subject}': {str(e)}", exc_info=True)
            return False
    
    # ==============================
    # ADMIN NOTIFICATIONS
    # ==============================
    
    def notify_admin_new_dispute(self, dispute: Dispute) -> bool:
        """
        Kirim email ke admin ketika ada dispute baru.
        
        Args:
            dispute: Dispute object yang baru dibuat
            
        Returns:
            bool: Success status
        """
        if not self.admin_emails:
            logger.warning("[EMAIL] No admin emails configured")
            return False
        
        subject = f"🚨 New Dispute #{dispute.id} - Review Required"
        
        # Plain text version
        message = f"""
New Dispute Submitted - Action Required

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DISPUTE DETAILS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Dispute ID: #{dispute.id}
Status: {dispute.status.upper()}
Created: {dispute.created_at.strftime('%Y-%m-%d %H:%M:%S')}

Reporter Information:
- Name: {dispute.reporter_name or 'Anonymous'}
- Email: {dispute.reporter_email or 'Not provided'}

Claim Text:
"{dispute.claim_text[:200]}{'...' if len(dispute.claim_text) > 200 else ''}"

User Feedback:
{dispute.user_feedback}

Supporting Evidence:
- DOI: {dispute.supporting_doi or 'None'}
- URL: {dispute.supporting_url or 'None'}
- File: {'Yes' if dispute.supporting_file else 'No'}

Original Verification:
- Label: {dispute.original_label or 'N/A'}
- Confidence: {f"{dispute.original_confidence * 100:.1f}%" if dispute.original_confidence else 'N/A'}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ACTION REQUIRED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Please review this dispute in the admin panel:
{settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS else 'localhost:8000'}/admin/disputes/{dispute.id}

Best regards,
Healthify System
        """
        
        # HTML version (optional, lebih bagus)
        html_message = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px; background: #f9f9f9;">
                <div style="background: #dc2626; color: white; padding: 20px; border-radius: 8px 8px 0 0;">
                    <h2 style="margin: 0;">🚨 New Dispute #{dispute.id}</h2>
                    <p style="margin: 5px 0 0 0;">Review Required</p>
                </div>
                
                <div style="background: white; padding: 20px; border-radius: 0 0 8px 8px;">
                    <h3 style="color: #dc2626; border-bottom: 2px solid #dc2626; padding-bottom: 10px;">
                        Dispute Details
                    </h3>
                    
                    <table style="width: 100%; margin: 15px 0;">
                        <tr>
                            <td style="padding: 8px; font-weight: bold; width: 150px;">Dispute ID:</td>
                            <td style="padding: 8px;">#{dispute.id}</td>
                        </tr>
                        <tr style="background: #f9f9f9;">
                            <td style="padding: 8px; font-weight: bold;">Status:</td>
                            <td style="padding: 8px;">
                                <span style="background: #fbbf24; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px;">
                                    {dispute.status.upper()}
                                </span>
                            </td>
                        </tr>
                        <tr>
                            <td style="padding: 8px; font-weight: bold;">Created:</td>
                            <td style="padding: 8px;">{dispute.created_at.strftime('%Y-%m-%d %H:%M:%S')}</td>
                        </tr>
                        <tr style="background: #f9f9f9;">
                            <td style="padding: 8px; font-weight: bold;">Reporter:</td>
                            <td style="padding: 8px;">{dispute.reporter_name or 'Anonymous'}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px; font-weight: bold;">Email:</td>
                            <td style="padding: 8px;">{dispute.reporter_email or 'Not provided'}</td>
                        </tr>
                    </table>
                    
                    <div style="background: #eff6ff; border-left: 4px solid #3b82f6; padding: 15px; margin: 15px 0;">
                        <h4 style="margin: 0 0 10px 0; color: #1e40af;">Claim Text</h4>
                        <p style="margin: 0; font-style: italic;">
                            "{dispute.claim_text[:200]}{'...' if len(dispute.claim_text) > 200 else ''}"
                        </p>
                    </div>
                    
                    <div style="background: #fef3c7; border-left: 4px solid #f59e0b; padding: 15px; margin: 15px 0;">
                        <h4 style="margin: 0 0 10px 0; color: #92400e;">User Feedback</h4>
                        <p style="margin: 0;">
                            {dispute.user_feedback}
                        </p>
                    </div>
                    
                    <div style="margin: 20px 0; text-align: center;">
                        <a href="http://{settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS else 'localhost:8000'}/admin/disputes/{dispute.id}" 
                           style="display: inline-block; background: #dc2626; color: white; padding: 12px 30px; text-decoration: none; border-radius: 6px; font-weight: bold;">
                            Review Dispute →
                        </a>
                    </div>
                    
                    <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 20px 0;">
                    
                    <p style="color: #6b7280; font-size: 12px; text-align: center; margin: 0;">
                        This is an automated notification from Healthify System.<br>
                        Please do not reply to this email.
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return self._send_email(
            subject=subject,
            message=message,
            recipient_list=self.admin_emails,
            html_message=html_message
        )
    
    def notify_admin_system_error(self, error_type: str, error_message: str, 
                                  context: Optional[Dict[str, Any]] = None) -> bool:
        """
        Kirim email ke admin ketika terjadi system error.
        
        Args:
            error_type: Tipe error (e.g., 'Verification Failed', 'Database Error')
            error_message: Pesan error detail
            context: Additional context information
            
        Returns:
            bool: Success status
        """
        if not self.admin_emails:
            return False
        
        subject = f"⚠️ System Error: {error_type}"
        
        context_str = ""
        if context:
            context_str = "\n\nContext:\n" + "\n".join([f"- {k}: {v}" for k, v in context.items()])
        
        message = f"""
System Error Detected

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ERROR DETAILS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Type: {error_type}
Time: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}

Error Message:
{error_message}
{context_str}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Please investigate this issue as soon as possible.

Best regards,
Healthify System
        """
        
        return self._send_email(
            subject=subject,
            message=message,
            recipient_list=self.admin_emails
        )
    
    # ==============================
    # USER NOTIFICATIONS
    # ==============================
    
    def notify_user_dispute_approved(self, dispute: Dispute, admin_notes: str = "") -> bool:
        """
        Kirim email ke user ketika dispute mereka di-approve.
        
        Args:
            dispute: Dispute object yang di-approve
            admin_notes: Catatan dari admin
            
        Returns:
            bool: Success status
        """
        if not dispute.reporter_email:
            logger.info(f"[EMAIL] No email for dispute #{dispute.id}, skipping user notification")
            return False
        
        subject = f"✅ Your Dispute #{dispute.id} Has Been Approved"
        
        # Build verification change info
        verification_change = ""
        if dispute.claim and hasattr(dispute.claim, 'verification_result'):
            vr = dispute.claim.verification_result
            verification_change = f"""
The verification result has been updated:
- New Label: {vr.label.upper()}
- New Confidence: {vr.confidence * 100:.1f}%
- Previous Label: {dispute.original_label or 'N/A'}
- Previous Confidence: {f"{dispute.original_confidence * 100:.1f}%" if dispute.original_confidence else 'N/A'}
            """
        
        admin_notes_section = f"\n\nAdmin Notes:\n{admin_notes}" if admin_notes else ""
        
        message = f"""
Dear {dispute.reporter_name or 'User'},

Good news! Your dispute regarding the claim verification has been approved by our admin team.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DISPUTE DETAILS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Dispute ID: #{dispute.id}
Status: APPROVED ✅
Reviewed: {dispute.reviewed_at.strftime('%Y-%m-%d %H:%M:%S') if dispute.reviewed_at else 'Just now'}

Your Claim:
"{dispute.claim_text[:200]}{'...' if len(dispute.claim_text) > 200 else ''}"

Your Feedback:
{dispute.user_feedback}
{verification_change}
{admin_notes_section}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Thank you for helping us improve the accuracy of Healthify!

Your contribution makes our platform more reliable for everyone.

Best regards,
Healthify Team
        """
        
        # HTML version
        html_message = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px; background: #f9f9f9;">
                <div style="background: #10b981; color: white; padding: 20px; border-radius: 8px 8px 0 0;">
                    <h2 style="margin: 0;">✅ Dispute Approved!</h2>
                    <p style="margin: 5px 0 0 0;">Your feedback has been reviewed</p>
                </div>
                
                <div style="background: white; padding: 20px; border-radius: 0 0 8px 8px;">
                    <p>Dear {dispute.reporter_name or 'User'},</p>
                    
                    <p>Good news! Your dispute regarding the claim verification has been <strong>approved</strong> by our admin team.</p>
                    
                    <div style="background: #d1fae5; border-left: 4px solid #10b981; padding: 15px; margin: 20px 0;">
                        <h4 style="margin: 0 0 10px 0; color: #065f46;">Status: APPROVED ✅</h4>
                        <p style="margin: 0; font-size: 14px; color: #047857;">
                            Dispute ID: #{dispute.id}<br>
                            Reviewed: {dispute.reviewed_at.strftime('%Y-%m-%d %H:%M') if dispute.reviewed_at else 'Just now'}
                        </p>
                    </div>
                    
                    <h3 style="color: #1f2937; border-bottom: 2px solid #e5e7eb; padding-bottom: 10px;">
                        Your Claim
                    </h3>
                    <p style="background: #f3f4f6; padding: 15px; border-radius: 6px; font-style: italic;">
                        "{dispute.claim_text[:200]}{'...' if len(dispute.claim_text) > 200 else ''}"
                    </p>
                    
                    {f'''
                    <h3 style="color: #1f2937; border-bottom: 2px solid #e5e7eb; padding-bottom: 10px; margin-top: 20px;">
                        Verification Updated
                    </h3>
                    <table style="width: 100%; background: #eff6ff; padding: 15px; border-radius: 6px;">
                        <tr>
                            <td style="padding: 5px; font-weight: bold;">New Label:</td>
                            <td style="padding: 5px;">{dispute.claim.verification_result.label.upper()}</td>
                        </tr>
                        <tr>
                            <td style="padding: 5px; font-weight: bold;">New Confidence:</td>
                            <td style="padding: 5px;">{dispute.claim.verification_result.confidence * 100:.1f}%</td>
                        </tr>
                    </table>
                    ''' if dispute.claim and hasattr(dispute.claim, 'verification_result') else ''}
                    
                    {f'''
                    <div style="background: #fef3c7; border-left: 4px solid #f59e0b; padding: 15px; margin: 20px 0;">
                        <h4 style="margin: 0 0 10px 0; color: #92400e;">Admin Notes</h4>
                        <p style="margin: 0;">{admin_notes}</p>
                    </div>
                    ''' if admin_notes else ''}
                    
                    <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 20px 0;">
                    
                    <p style="color: #059669; font-weight: bold;">
                        Thank you for helping us improve the accuracy of Healthify! 🙏
                    </p>
                    
                    <p style="color: #6b7280; font-size: 12px; text-align: center; margin: 20px 0 0 0;">
                        This is an automated notification from Healthify System.<br>
                        Please do not reply to this email.
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return self._send_email(
            subject=subject,
            message=message,
            recipient_list=[dispute.reporter_email],
            html_message=html_message
        )
    
    def notify_user_dispute_rejected(self, dispute: Dispute, admin_notes: str = "") -> bool:
        """
        Kirim email ke user ketika dispute mereka di-reject.
        
        Args:
            dispute: Dispute object yang di-reject
            admin_notes: Alasan rejection dari admin
            
        Returns:
            bool: Success status
        """
        if not dispute.reporter_email:
            logger.info(f"[EMAIL] No email for dispute #{dispute.id}, skipping user notification")
            return False
        
        subject = f"❌ Your Dispute #{dispute.id} Update"
        
        admin_notes_section = f"\n\nReason:\n{admin_notes}" if admin_notes else "\n\nNo specific reason provided."
        
        message = f"""
            Dear {dispute.reporter_name or 'User'},

            Thank you for your feedback. After careful review, our admin team has decided to maintain the original verification result for this claim.

            ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            DISPUTE DETAILS
            ━━━━━━━━━━━━━━━━━━━━━━━━━━━━

            Dispute ID: #{dispute.id}
            Status: NOT APPROVED ❌
            Reviewed: {dispute.reviewed_at.strftime('%Y-%m-%d %H:%M:%S') if dispute.reviewed_at else 'Just now'}

            Your Claim:
            "{dispute.claim_text[:200]}{'...' if len(dispute.claim_text) > 200 else ''}"

            Your Feedback:
            {dispute.user_feedback}
            {admin_notes_section}

            Original Verification Result (Maintained):
            - Label: {dispute.original_label or 'N/A'}
            - Confidence: {f"{dispute.original_confidence * 100:.1f}%" if dispute.original_confidence else 'N/A'}

            ━━━━━━━━━━━━━━━━━━━━━━━━━━━━

            We appreciate your concern and value your input. If you have additional evidence or would like to submit another dispute, please feel free to do so.

            Best regards,
            Healthify Team
                    """
        
        # HTML version
        html_message = f"""
            <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px; background: #f9f9f9;">
                    <div style="background: #ef4444; color: white; padding: 20px; border-radius: 8px 8px 0 0;">
                        <h2 style="margin: 0;">Dispute Update</h2>
                        <p style="margin: 5px 0 0 0;">Dispute #{dispute.id}</p>
                    </div>
                    
                    <div style="background: white; padding: 20px; border-radius: 0 0 8px 8px;">
                        <p>Dear {dispute.reporter_name or 'User'},</p>
                        
                        <p>Thank you for your feedback. After careful review, our admin team has decided to <strong>maintain the original verification result</strong> for this claim.</p>
                        
                        <div style="background: #fee2e2; border-left: 4px solid #ef4444; padding: 15px; margin: 20px 0;">
                            <h4 style="margin: 0 0 10px 0; color: #991b1b;">Status: Not Approved ❌</h4>
                            <p style="margin: 0; font-size: 14px; color: #b91c1c;">
                                Dispute ID: #{dispute.id}<br>
                                Reviewed: {dispute.reviewed_at.strftime('%Y-%m-%d %H:%M') if dispute.reviewed_at else 'Just now'}
                            </p>
                        </div>
                        
                        <h3 style="color: #1f2937; border-bottom: 2px solid #e5e7eb; padding-bottom: 10px;">
                            Your Claim
                        </h3>
                        <p style="background: #f3f4f6; padding: 15px; border-radius: 6px; font-style: italic;">
                            "{dispute.claim_text[:200]}{'...' if len(dispute.claim_text) > 200 else ''}"
                        </p>
                        
                        {f'''
                        <div style="background: #fef3c7; border-left: 4px solid #f59e0b; padding: 15px; margin: 20px 0;">
                            <h4 style="margin: 0 0 10px 0; color: #92400e;">Reason for Decision</h4>
                            <p style="margin: 0;">{admin_notes}</p>
                        </div>
                        ''' if admin_notes else ''}
                        
                        <h3 style="color: #1f2937; border-bottom: 2px solid #e5e7eb; padding-bottom: 10px; margin-top: 20px;">
                            Original Verification (Maintained)
                        </h3>
                        <table style="width: 100%; background: #f3f4f6; padding: 15px; border-radius: 6px;">
                            <tr>
                                <td style="padding: 5px; font-weight: bold;">Label:</td>
                                <td style="padding: 5px;">{dispute.original_label or 'N/A'}</td>
                            </tr>
                            <tr>
                                <td style="padding: 5px; font-weight: bold;">Confidence:</td>
                                <td style="padding: 5px;">{f"{dispute.original_confidence * 100:.1f}%" if dispute.original_confidence else 'N/A'}</td>
                            </tr>
                        </table>
                        
                        <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 20px 0;">
                        
                        <p style="color: #6b7280;">
                            We appreciate your concern and value your input. If you have additional evidence or would like to submit another dispute, please feel free to do so.
                        </p>
                        
                        <p style="color: #6b7280; font-size: 12px; text-align: center; margin: 20px 0 0 0;">
                            This is an automated notification from Healthify System.<br>
                            Please do not reply to this email.
                        </p>
                    </div>
                </div>
            </body>
            </html>
        """
        
        return self._send_email(
            subject=subject,
            message=message,
            recipient_list=[dispute.reporter_email],
            html_message=html_message
        )


# Singleton instance
email_service = EmailNotificationService()