"""
Offline regression tests for the SMS parser.

Every case comes from a real SMS observed in production (Supabase audit,
Sept 2026). Run with:  python test_sms_parser.py
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))

from sms_parser.sms_parser import SMSParser

# (expect_skip, expect_merchant, expect_payment_mode, description, sms_body)
# expect_payment_mode None = not asserted
CASES = [
    # ── Non-transactions that must be skipped ────────────────────────────
    (True, None, None, "Mandate Set",       "Mandate Set\nRs.4000.00\nFor Google Play\nFrom HDFC Bank A/c x1029"),
    (True, None, None, "Limit modified",    "Limit modified: Online international transactions On HDFC Bank Credit Card ending 8229. New limit: Rs. 30,000"),
    (True, None, None, "Limit increase",    "Manage spends effectively by increasing the limit on ICICI Bank Credit Card XX3008 from Rs920000 to Rs1000000"),
    (True, None, None, "Declined card txn", "Transaction of Rs. 564.85 Declined on HDFC Bank Credit Card xx8229 as Merchant is Non-Compliant"),
    (True, None, None, "Declined transfer", "Declined: Your money transfer of INR 5,000.00 on 01-05-26. Reason:Invalid IFSC"),
    (True, None, None, "NSE fund balance",  "INDSTOCKSPRIVATELIMITED on 02-05-2026 reported your Fund bal Rs.334.150 & Securities bal 0.000"),
    (True, None, None, "BSE trade confirm", "BSE Trade Confirmation Client Code 4DYN9XZ0Y6 - Broker 6779 - EQ Value Rs 14304.00"),
    (True, None, None, "EPF passbook",      "Dear member, your passbook balance against PY is Rs. 76,194/-. Contribution of Rs. 3,600"),
    (True, None, None, "CDSL e-voting",     "Dear Investor, e-Voting for ONGC-EQ-RS.5/- begins from 27-08-2026"),
    (True, None, None, "SIP due notice",    "Dear Investor, SIP of Rs.5000 dated 07-09-2026 under Folio 9723898 is due for debit from your bank"),
    (True, None, None, "Insurance quote",   "Thank you for your Quotation with TATA AIG Motor Insurance. Your Premium amount Rs 5000"),
    (True, None, None, "Airtel bill gen",   "Hi Ayush Varma, Bill for your Airtel Black plan dated 27-Aug-2026 has been generated Rs 2827"),
    (True, None, None, "Airtel roaming",    "Hi, thank you for purchasing Rs. 2999 International Roaming pack for Airtel Mobile"),
    (True, None, None, "Airtel processing", "Hi, we have processed Rs. 2827.28 for your Airtel Mobile. The payment will be updated within 5 minutes"),
    (True, None, None, "Airtel multi conn", "Hi, bill payment of Rs. 2827.28 paid through Upi towards your multiple Airtel connections has been processed"),
    (True, None, None, "PNB deposit ack",   "Thanks for depositing an amount of Rs. 39466 against your Loan Ac XX1435"),
    (True, None, None, "OTP",               "OTP is 477094 for txn of INR 1022.00 at WWW MYNTRA on HDFC Bank card ending 8229"),
    (True, None, None, "Balance alert",     "Available Bal in HDFC Bank A/c XX1029 as on yesterday:20-APR-26 is INR 5,87,634.99. Cheques are subject to clearing."),

    # ── Real transactions with fixed-label merchants ─────────────────────
    (False, "Card Bill Payment", "Credit Card", "HDFC card bill recv", "DEAR HDFCBANK CARDMEMBER, PAYMENT OF Rs. 30000.00 RECEIVED TOWARDS YOUR CREDIT CARD ENDING WITH 8229 ON 29-8-2026"),
    (False, "Card Bill Payment", None, "SBM card bill recv", "Dear Customer, Payment credit received of INR 2681.45 for your SBM Niyo Global Credit Card. Available Credit Limit is INR 100000"),
    (False, "Income Tax Refund", "NEFT", "IT refund NEFT",   "Update! INR 93,060.00 deposited in HDFC Bank A/c XX1029 on 22-AUG-26 for NEFT Cr-SBIN0000TBU-ITDTAX REFUND 2026-27"),
    (False, "Term Deposit", None, "SBM TD funding",          "Your account XXXXXXXXXX3047 is debited with INR 10000. on 2026-05-19 infor :TD FUND FOR A/c 20012625809993"),
    (False, "Fund Transfer", None, "SBM IFT",                "Your account XXXXXXXXXX3047 is debited with INR 4856.54. on 2026-05-09 infor :IFT/A4D91130D06D47A4"),
    (False, "ATM Withdrawal", "ATM", "SBM intl ATM",         "Your account XXXXXXXXXX3047 is debited with INR 7488.24. on 2026-05-18 infor :165744/613811984914/00000000/ATMISS/So 186-188 Le"),
    (False, "ATM Charges", "ATM", "ATM charges",             "Your account XXXXXXXXXX3047 is debited with INR 423. infor :613811984914/ATM Cash Withdrawal Charges"),
    (False, "Forex Remittance", None, "HDFC forex RFX",      "UPDATE: INR 24,987.26 debited from HDFC Bank XX1029 on 07-MAY-26. Info: RFX 070526BTT02434 USD261.25@95.645"),
    (False, "Nippon India MF", None, "Nippon MF purchase",   "Addlt. Purchase txn of Rs.1,000.00, dtd 15/05/2026 has been processed. Click https://x for more details on txn. Nippon India MF"),
    (False, "ICICI Prudential MF", None, "IPru SIP",         "Dear Investor, Your SIP Purchase of Rs.4,999.75 in Folio 9723898 in Multicap Fund - Growth has been processed"),
    (False, "Zomato", None, "Zomato Money add",              "Rs. 25.88 added to Zomato Money (on mobile ending with **1400). This balance expires on 25 May 2026."),
    (False, "Zomato Refund", None, "Zomato order refund",    "Refund of Rs. 307.38 for your Zomato order from Olio - The Wood Fired Pizzeria has been initiated"),
    (False, "TATA AIA Life Insurance", None, "Policy debit", "Ayush Varma payment of Rs.1929 for your TATA AIA Life policy no. C222716282 has been successfully debited"),
    (False, "IMPS Reversal", "IMPS", "IMPS reversal",        "Update! INR 5,000.00 deposited in HDFC Bank A/c XX1029 on 01-MAY-26 for Rev-IMPS-612155478550-Swati Jha-ESFB"),
    (True, None, None, "ITD challan dup",                    "Dear User,\nChallan payment of Rs. 5610 against PAN/TAN AIXXXXXX6N for Assessment Year 2025 has been successfully paid.\ne-Filing, ITD."),

    # ── Account transfers ────────────────────────────────────────────────
    (False, "Transfer to A/c 8064", "IMPS", "HDFC IMPS out", "IMPS INR 54,500.00 sent from HDFC Bank A/c XX1029 on 31-08-26 To A/c xxxxxxxxxx8064 Ref-624331431734"),
    (False, "Transfer to A/c 8702", "UPI", "HDFC UPI to a/c","HDFC Bank:Rs. 100.00 debited from a/c *1029 on 28/04/26 to a/c **8702 (UPI Ref No. 611823711516)"),

    # ── Merchant extraction / normalisation ──────────────────────────────
    (False, "Cochin Zen Hotel", "Credit Card", "SBM padded name", "Dear Customer, You have paid INR 16434.04 at COCHIN ZEN HOTEL         HO through your SBM Niyo Global Credit Card"),
    (False, "Grab", "Credit Card", "SBM Grab* code",         "Dear Customer, You have paid INR 485.08 at Grab* A-9BUSWUOWWID9AV   00    through your SBM Niyo Global Credit Card"),
    (False, "Phoenix Market City", None, "IDBI FASTag",      "Dear Customer, Your IDBI BANK NETC FASTag linked vehicle no. KA03NW3612, has been debited with Rs. 120/- at Phoenix Market City on 09-05-2026 14:51"),
    (False, "Blinkit", "Credit Card", "HDFC card GROFERSI",  "Spent Rs.260 On HDFC Bank Card 8229 At GROFERSI6108222 On 2026-08-23:12:30:44.Not You? To Block"),
    (False, "Amma Shop", "Credit Card", "HDFC card dotted",  "Spent Rs.770 On HDFC Bank Card 8229 At ..ARTICULTURAL FRU_ On 2026-04-26:20:15:16.Not You?"),
    (False, "Amazon", "Credit Card", "ICICI card spend", "INR 3,276.00 spent using ICICI Bank Card XX3008 on 19-Apr-26 on AMAZON PAY IN G. Avl Limit: INR 9,14,593.67."),
    (False, "Swati Jha", "UPI", "HDFC UPI multiline",        "Sent Rs.100.00\nFrom HDFC Bank A/C *1029\nTo Swati Jha\nOn 05/04/26\nRef 121125016650\nNot You?\nCall 18002586161/SMS BLOCK UPI to 7308080808"),
    (False, "Swati Jha", "IMPS", "IDFC debit not skipped",   "Your A/c XX5865 debited by Rs. 10.00 on 05/04/26; Swati Jha credited. RRN 646195971777. Available balance Rs. 3,54,576.62. Team IDFC FIRST Bank"),

    # ── Second audit round (user-reviewed, Sept 2026) ────────────────────
    (True, None, None, "PNB EMI UMRN dup",   "PAYMENT ALERT! \nINR 39466.00 deducted from HDFC Bank A/C No 1029 towards PUNJAB NATIONAL BANK UMRN: HDFC7012206251001058"),
    (True, None, None, "SBI IT refund dup",  "Dear Customer, For PAN XXXXXX146N, An IT Refund amount of Rs 93060 for AY-2026-27 has been credited to your account XXXXXXXXXX1029 on 2026-08-21. -SBI"),
    (False, "Anthropic", "Credit Card", "USD card spend",    "USD 5.90 spent using ICICI Bank Card XX3008 on 22-Aug-26 on ANTHROPIC. Avl Limit: INR 9,15,832.31. If not you, call 1800 2662/SMS BLOCK 3008 to 9215676766."),
    (False, "Amazon", "Credit Card", "ICICI new at-format",  "Rs 5,499.00 spent on ICICI Bank Card XX3008 on 24-Aug-26 at AMAZON PAY IN G. Avl Lmt: Rs 9,10,320.05. To dispute, call 18002662/SMS BLOCK 3008 to 9215676766. To convert this txn to EMI give a missed call on 992"),
    (False, "Amazon", "Credit Card", "ICICI apay variant E", "INR 3,461.24 spent using ICICI Bank Card XX3008 on 05-May-26 on AMAZON PAY IN E. Avl Limit: INR 9,01,899.05. If not you, call 1800 2662/SMS BLOCK 3008 to 9215676766."),
    (False, "79 Nhu Y", "Credit Card", "SBM digit-start",    "Dear Customer, You have paid INR 1147.83 at 79 NHU Y                 HO through your SBM Niyo Global Credit Card. In case you have not initiated this transaction, report at customercare@sbmbank.co.in"),
    (False, "Cu Chi Tunnels", "Credit Card", "SBM K DTLS",   "Dear Customer, You have paid INR 8198.80 at K DTLS DIA DAO CU CHI    HO through your SBM Niyo Global Credit Card. In case you have not initiated this transaction, report at customercare@sbmbank.co.in"),
    (False, "Grab", "Credit Card", "SBM reversal credit",    "Dear Customer, reversal of INR 3.59 is credited to your SBM Niyo Global Credit Card due to failed transaction at GRAB                     00   . Available limit is INR 54000.00 SBM Bank India"),
    (False, "Card Bill Payment", None, "HDFC card credited", "HDFC Bank Cardmember, Payment of Rs 30000 was credited to your card ending 8229 on 29/AUG/2026."),
    (False, "AVG Antivirus", "Credit Card", "AVG spend",     "INR 900.00 spent using ICICI Bank Card XX3008 on 12-Apr-26 on AVG. Avl Limit: INR 8,83,170.46. If not you, call 1800 2662/SMS BLOCK 3008 to 9215676766."),
]


def main() -> int:
    parser = SMSParser()
    fails = 0
    for exp_skip, exp_merchant, exp_mode, desc, sms in CASES:
        skip = parser._should_skip(sms)
        if skip != exp_skip:
            print(f"FAIL [{desc}]: skip={skip}, expected {exp_skip}")
            fails += 1
            continue
        if exp_skip:
            continue
        merchant = parser._extract_merchant(sms)
        mode = parser._extract_payment_mode(sms)
        if merchant != exp_merchant:
            print(f"FAIL [{desc}]: merchant={merchant!r}, expected {exp_merchant!r}")
            fails += 1
        if exp_mode is not None and mode != exp_mode:
            print(f"FAIL [{desc}]: payment_mode={mode!r}, expected {exp_mode!r}")
            fails += 1

    if fails:
        print(f"\n{fails} failure(s) across {len(CASES)} cases.")
        return 1
    print(f"All {len(CASES)} cases passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
