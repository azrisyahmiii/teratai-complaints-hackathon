"""English reply templates (SPEC §4.6). One dict entry per template key; placeholders are filled by `templates.context`.

Wording rules: <= 120 words, only facts from the fact sheet, never a refund promise unless the key says REFUND, no internal
terms. Regulatory contacts are limited to the verified ones in `check.py` (NSRC 997, FMOS, BNMLINK 1-300-88-5465).
"""

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]  # fmt: skip

OPEN = "Dear {who},\n\nThank you for contacting Teratai Bank. "
CLOSE = "\n\nYours sincerely,\nTeratai Bank"

REDRESS = (
    "If you are not satisfied with this outcome, you may refer the matter to the Financial Markets Ombudsman "
    "Service (FMOS) or contact BNMLINK at 1-300-88-5465."
)
# Fee disputes: FMOS excludes "fees & charges" (commercial decisions; fmos.org.my FAQ Q9), so only BNMLINK is offered.
REDRESS_BNM = "If you are not satisfied with this outcome, you may contact BNMLINK at 1-300-88-5465."
SCAM_HELP = (
    "Please also call the National Scam Response Centre (NSRC) at 997 and, if advised, lodge a police report."
)
REFUND_TIME = "within {sla_days} working days"

TEXTS: dict[str, str] = {
    "DUPLICATE_CHARGE.REFUND": OPEN
    + "We reviewed your card charges{at} and confirmed that transaction {txn} of {amount} on {date} was charged twice. "
    "We will refund {refund} to your account " + REFUND_TIME + "." + CLOSE,
    "DUPLICATE_CHARGE.DECLINE.reversed": OPEN
    + "We reviewed card transaction {txn} of {amount}{at} on {date}. The duplicate charge was already reversed on "
    "{rev_date}, so no further refund is due. {redress}" + CLOSE,
    "DUPLICATE_CHARGE.DECLINE.single": OPEN
    + "We reviewed card transaction {txn} of {amount}{at} on {date} but found no identical earlier charge. It appears "
    "to be a single valid purchase, so we are unable to refund it. {redress}" + CLOSE,
    "DUPLICATE_CHARGE.DECLINE.apart": OPEN
    + "We reviewed card transaction {txn} of {amount}{at} on {date}. A similar charge exists, but the two were not made "
    "close enough together to be a duplicate charge, so we are unable to refund it. {redress}" + CLOSE,
    "FAILED_TRANSFER.REFUND": OPEN
    + "We confirmed that your transfer{to} of {amount} on {date} (transaction {txn}) failed and the money was not "
    "returned to you. We will refund {refund} to your account " + REFUND_TIME + "." + CLOSE,
    "FAILED_TRANSFER.DECLINE.reversed": OPEN
    + "Your transfer{to} of {amount} on {date} (transaction {txn}) did not go through, and the money was returned to "
    "your account on {rev_date}. No further refund is due. {redress}" + CLOSE,
    "FAILED_TRANSFER.DECLINE.completed": OPEN
    + "Our records show that your transfer{to} of {amount} on {date} (transaction {txn}) was completed and the money "
    "reached the recipient's bank, so we are unable to refund it. {redress}" + CLOSE,
    "ATM_NOT_DISPENSED.REFUND": OPEN
    + "The ATM records for transaction {txn} on {date} show that you requested {requested} but only {dispensed} was "
    "dispensed. We will refund the shortfall of {refund} to your account " + REFUND_TIME + "." + CLOSE,
    "ATM_NOT_DISPENSED.DECLINE": OPEN
    + "The ATM records for transaction {txn} on {date} show that the full {requested} was dispensed, so we are unable "
    "to refund it. {redress}" + CLOSE,
    "UNAUTHORISED_CARD.REFUND": OPEN
    + "We reviewed card transaction {txn} of {amount}{at} on {date}, which was processed without authentication. We will "
    "refund {refund} to your account " + REFUND_TIME + "." + CLOSE,
    "UNAUTHORISED_CARD.INVESTIGATE": OPEN
    + "We have received your report about card transaction {txn} of {amount}{at} on {date}. Our fraud team is "
    "investigating and will contact you within {sla_days} working days, then update you at least every "
    "{update_days} working days. No decision on a refund has been made yet. Please keep your card safe and tell us at once about any other transaction you do not recognise."
    + CLOSE,
    "SCAM_TRANSFER.INVESTIGATE": OPEN
    + "We are very sorry to hear this. Our fraud team has started investigating your transfer{to} of {amount} on {date} "
    "(transaction {txn}) and will attempt to recall the funds, although recovery cannot be guaranteed. {scam_help} "
    "We will update you at least every {update_days} working days until the investigation is complete."
    + CLOSE,
    "FEE_DISPUTE.REFUND": OPEN
    + "We reviewed fee transaction {txn} of {charged} on {date}. The fee due on your account was {due}. We will "
    "refund the difference of {refund} " + REFUND_TIME + "." + CLOSE,
    "FEE_DISPUTE.REFUND.waived": OPEN
    + "We reviewed fee transaction {txn} of {charged} on {date}. No fee was due on your account, so we will refund "
    "{refund} " + REFUND_TIME + "." + CLOSE,
    "FEE_DISPUTE.DECLINE": OPEN
    + "We reviewed fee transaction {txn} of {charged} on {date}. The fee is in line with our fee schedule for your "
    "account, so we are unable to refund it. {redress_bnm}" + CLOSE,
    "SERVICE_QUALITY.INFO_ONLY": OPEN
    + "We are sorry about the experience you described. We have recorded your feedback and passed it to the team "
    "concerned, who will review it and respond within {sla_days} working days." + CLOSE,
    "NEEDS_INFO": OPEN
    + "To look into your complaint we need a little more information. Please reply with the date of the transaction, "
    "the amount and the name of the merchant or recipient. Once we have these details we will review your case within "
    "{sla_days} working days." + CLOSE,
    "NEEDS_INFO.SCAM": OPEN
    + "To look into your complaint we need a little more information. Please reply with the date of the transaction, "
    "the amount and the name of the recipient. {scam_help}" + CLOSE,
    "WRONG_CUSTOMER": OPEN
    + "We could not match the card or account mentioned in your message to your own accounts with us, so we have made "
    "no decision yet. Please reply with the last 4 digits of your own card or your account details so that we can "
    "verify them. If your complaint concerns a family member's or another person's account, we can only discuss it "
    "with the account holder, who is welcome to contact the bank directly." + CLOSE,
    "NOT_COMPLAINT": "Dear {who},\n\nThank you for your message. We could not find a complaint or request in it. If you "
    "need help with your account, please reply with the details and we will assist you." + CLOSE,
    "GENERIC": OPEN
    + "We have received your complaint and our team is reviewing it. We will update you within "
    "{sla_days} working days." + CLOSE,
}
