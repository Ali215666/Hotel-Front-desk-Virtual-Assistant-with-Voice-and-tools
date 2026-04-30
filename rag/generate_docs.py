"""
STEP 1 — Generate 50 hotel SOP/FAQ documents and save to /data/docs/.

Distribution:
  Hotel Policies   : 10 docs (doc_001 – doc_010)
  Booking Rules    : 10 docs (doc_011 – doc_020)
  Check-in/out     :  8 docs (doc_021 – doc_028)
  Payment Rules    :  7 docs (doc_029 – doc_035)
  Amenities        :  5 docs (doc_036 – doc_040)
  FAQs             : 10 docs (doc_041 – doc_050)
"""

import os
import pathlib

# ---------------------------------------------------------------------------
# Document corpus — 50 unique, realistic hotel SOP / FAQ snippets
# ---------------------------------------------------------------------------

DOCUMENTS = [
    # ── Hotel Policies (10) ──────────────────────────────────────────────
    (
        "doc_001",
        """Cancellation Policy
Guests may cancel their reservation free of charge if the request is made at least 48 hours
before the scheduled check-in date. Cancellations within 48 hours will incur a penalty
equivalent to one night's room rate.""",
    ),
    (
        "doc_002",
        """No-Show Policy
Guests who fail to arrive on the check-in date without prior notification will be charged
the full reservation amount. The room will be released after 11:00 PM on the check-in date
if no contact has been made by the guest.""",
    ),
    (
        "doc_003",
        """Refund Policy
Approved refunds are processed within 7–10 business days to the original payment method.
Refunds for cash payments will be issued as bank transfers or cheques upon request.""",
    ),
    (
        "doc_004",
        """Pet Policy
Pets are not permitted anywhere on hotel premises, including guest rooms, lobbies, and
dining areas. Service animals certified under local disability laws are the sole exception
and must be declared at the time of booking.""",
    ),
    (
        "doc_005",
        """Smoking Policy
This is a 100% smoke-free property. Smoking is strictly prohibited in all indoor areas,
including guest rooms and corridors. A cleaning fee of $250 will be charged to guests found
in violation of this policy.""",
    ),
    (
        "doc_006",
        """Guest Conduct Policy
Guests are expected to behave respectfully toward staff and other guests at all times.
The hotel reserves the right to remove any guest causing disturbance or damage without
refund.""",
    ),
    (
        "doc_007",
        """Visitor Policy
Registered guests may receive visitors between 08:00 and 22:00. Overnight visitors must be
registered at the front desk and are subject to an additional occupancy charge. The maximum
room occupancy as stated at booking must not be exceeded.""",
    ),
    (
        "doc_008",
        """Noise Policy
Quiet hours are observed daily from 22:00 to 08:00. Loud music, parties, and disruptive
activity during this period are prohibited. Repeated violations may result in the guest
being asked to vacate the property.""",
    ),
    (
        "doc_009",
        """Damage Policy
Guests are financially liable for any damage caused to hotel property during their stay.
Charges will be assessed at current replacement cost and billed to the credit card on file.
A damage inspection occurs after each checkout.""",
    ),
    (
        "doc_010",
        """Children Policy
Children under 12 stay free when sharing a room with at least one paying adult and using
existing bedding. Additional beds or cribs may be requested at an extra nightly charge.
Supervision of children is the full responsibility of accompanying adults.""",
    ),
    # ── Booking Rules (10) ────────────────────────────────────────────────
    (
        "doc_011",
        """Reservation Process
Reservations can be made online via our website, by phone, or directly at the front desk.
All bookings require a valid credit card to guarantee the reservation. Confirmation is sent
by email within 15 minutes of booking.""",
    ),
    (
        "doc_012",
        """Booking Modification Policy
Modifications to existing reservations (dates, room type) are allowed up to 24 hours before
check-in, subject to availability. Changes requested less than 24 hours before check-in
will be treated as a new booking and may incur additional charges.""",
    ),
    (
        "doc_013",
        """Peak Season Booking Rules
During peak season (June–August and December 20–January 5), a minimum stay of 3 nights is
required. Rates are non-negotiable during peak periods and full payment is collected at the
time of booking.""",
    ),
    (
        "doc_014",
        """Early Booking Discount
Guests who book 30 or more days in advance are eligible for a 10% early-bird discount.
The discount applies to the room rate only and cannot be combined with other promotions.
Early-booking rates are non-refundable.""",
    ),
    (
        "doc_015",
        """Group Booking Policy
Groups of 10 or more rooms must contact our events team directly for a group rate.
A signed contract and 25% deposit are required to hold group blocks. The remaining
balance is due 14 days before arrival.""",
    ),
    (
        "doc_016",
        """Corporate Booking Policy
Corporate accounts with a signed agreement receive negotiated rates year-round.
Invoices are issued monthly and payable within 30 days. Corporate rates require
a minimum of 5 room-nights per month to remain active.""",
    ),
    (
        "doc_017",
        """Online Booking Terms
Rates displayed online are per room per night and inclusive of VAT unless stated otherwise.
The hotel is not responsible for third-party booking errors. Guests are advised to book
directly for the best available rate guarantee.""",
    ),
    (
        "doc_018",
        """Waitlist Policy
When a desired room type is fully booked, guests may join a waitlist free of charge.
Waitlist guests are notified within 24 hours of a cancellation. Waitlist positions do not
guarantee availability.""",
    ),
    (
        "doc_019",
        """Promotional Rate Rules
Promotional rates are valid only during specified date ranges and cannot be applied to
existing bookings. All promotions are subject to availability and may be withdrawn at any
time without notice.""",
    ),
    (
        "doc_020",
        """Reservation Hold Policy
Reservations without a credit card guarantee are held until 18:00 on the day of arrival.
After that time, unclaimed rooms may be released to walk-in guests. Guaranteed reservations
are held until midnight on the check-in date.""",
    ),
    # ── Check-in / Check-out (8) ──────────────────────────────────────────
    (
        "doc_021",
        """Standard Check-in Time
Standard check-in time is 15:00 (3:00 PM). Early check-in before 15:00 is subject to
availability and may incur an additional half-day charge. Guests arriving before check-in
time may store luggage at the front desk complimentarily.""",
    ),
    (
        "doc_022",
        """Standard Check-out Time
Standard check-out time is 11:00 AM. Guests are kindly requested to vacate their rooms and
return key cards by this time. Late check-out requests must be made at the front desk the
evening before departure.""",
    ),
    (
        "doc_023",
        """Late Check-out Policy
Late check-out until 14:00 is available upon request at no charge, subject to availability.
Check-out between 14:00 and 18:00 is charged at 50% of the nightly rate. Check-out after
18:00 will be charged the full nightly rate.""",
    ),
    (
        "doc_024",
        """Early Check-in Policy
Early check-in from 08:00 may be arranged in advance for an additional fee. Requests
submitted at least 24 hours ahead are prioritised. The hotel cannot guarantee room
readiness before 12:00 for same-day early check-in requests.""",
    ),
    (
        "doc_025",
        """Express Check-in
Guests who complete online check-in 24 hours before arrival may proceed directly to their
room using a mobile key. Front desk assistance remains available should any issue arise.
Online check-in closes 2 hours before scheduled arrival.""",
    ),
    (
        "doc_026",
        """Express Check-out
Express check-out allows guests to leave the key card in the designated box at the lobby
without queuing. An itemised bill is emailed automatically. Disputes must be raised within
48 hours of check-out.""",
    ),
    (
        "doc_027",
        """Check-in Documentation
A valid government-issued photo ID is mandatory for all guests at check-in. International
guests must present a valid passport. The front desk may request additional identification
if the primary document is unclear.""",
    ),
    (
        "doc_028",
        """Room Assignment Policy
The hotel guarantees the room category booked, not a specific room number. Room assignments
are finalised on the day of arrival. Upgrade requests are honoured free of charge when
availability permits.""",
    ),
    # ── Payment Rules (7) ─────────────────────────────────────────────────
    (
        "doc_029",
        """Accepted Payment Methods
The hotel accepts Visa, MasterCard, American Express, and Discover credit and debit cards.
Cash payments in local currency are accepted at the front desk. Cryptocurrency and cheques
are not accepted.""",
    ),
    (
        "doc_030",
        """Security Deposit Policy
A security deposit of $100 per night (maximum $500) is pre-authorised on the guest's credit
card at check-in. The hold is released within 3–5 business days of checkout, provided no
damages or incidental charges apply.""",
    ),
    (
        "doc_031",
        """Billing and Invoicing
Itemised invoices are available at the front desk or via email upon request. Corporate
invoice requests must be submitted within 30 days of checkout. The hotel cannot amend
invoices after 60 days from the transaction date.""",
    ),
    (
        "doc_032",
        """Incidental Charges
Room service, minibar consumption, telephone calls, and laundry are charged as incidentals.
These are itemised on the final bill at checkout. Disputes must be raised before the guest
vacates the property.""",
    ),
    (
        "doc_033",
        """Advance Payment Policy
For stays longer than 7 nights, full payment for the entire stay is required at check-in.
Group bookings of 10 or more rooms require a 50% deposit 14 days before arrival. The
remaining balance is due on the check-in date.""",
    ),
    (
        "doc_034",
        """Currency Exchange
Limited currency exchange services are available at the front desk for major currencies.
Rates are updated daily and may differ from bank rates. The hotel is not responsible for
exchange rate fluctuations between booking and payment dates.""",
    ),
    (
        "doc_035",
        """Refund Timeline for Card Payments
Refunds to credit or debit cards are processed within 5–7 business days after approval.
Processing time may extend to 10 business days depending on the issuing bank. Guests are
advised to contact their bank if refunds are not received within 14 days.""",
    ),
    # ── Amenities (5) ────────────────────────────────────────────────────
    (
        "doc_036",
        """Wi-Fi Services
High-speed Wi-Fi is available throughout the hotel, including all guest rooms, lobbies, and
conference areas, at no additional charge. Network credentials are provided at check-in.
For technical assistance, dial extension 0 from any room phone.""",
    ),
    (
        "doc_037",
        """Fitness Centre
The fitness centre is open 24 hours and equipped with cardio machines, free weights, and
resistance equipment. Complimentary use is included for all registered guests. Towels and
water are provided; personal trainers are available by appointment.""",
    ),
    (
        "doc_038",
        """Swimming Pool
The outdoor pool is open daily from 07:00 to 21:00. Pool towels are available at the
poolside towel station. Guests are reminded that no lifeguard is on duty, and children
must be supervised by an adult at all times.""",
    ),
    (
        "doc_039",
        """Room Service
Room service is available 24 hours a day. Orders can be placed by dialling extension 7 from
the in-room phone or via the hotel app. A service charge of 15% and a delivery fee of $5
apply to all room service orders.""",
    ),
    (
        "doc_040",
        """Parking Facilities
Complimentary self-parking is available in the hotel's secure underground garage for all
registered guests. Valet parking is available at an additional charge of $25 per night.
The hotel is not liable for loss or damage to vehicles.""",
    ),
    # ── FAQs (10) ─────────────────────────────────────────────────────────
    (
        "doc_041",
        """FAQ: Is breakfast included?
Breakfast is included in select rate plans. Please check your booking confirmation to
confirm whether the breakfast package applies. If not included, buffet breakfast is
available in the restaurant from 06:30 to 10:30 for $18 per person.""",
    ),
    (
        "doc_042",
        """FAQ: Is parking free?
Complimentary self-parking is included for all registered hotel guests. Simply inform the
front desk of your vehicle registration at check-in. Valet parking is also available for
an additional nightly fee.""",
    ),
    (
        "doc_043",
        """FAQ: Are pets allowed?
Pets are not permitted at our property. Only certified service animals as defined by local
law are allowed and must be declared during the booking process. Undeclared service animals
may be subject to verification.""",
    ),
    (
        "doc_044",
        """FAQ: What is the cancellation deadline?
You may cancel your reservation at no charge if you do so at least 48 hours before your
scheduled check-in time. Late cancellations within 48 hours will result in a charge of one
night's room rate to your registered card.""",
    ),
    (
        "doc_045",
        """FAQ: Is there an airport shuttle?
A complimentary airport shuttle operates on fixed schedules. Guests must reserve a seat at
least 4 hours in advance by calling the front desk or using the hotel app. The shuttle
departs every 2 hours starting at 05:00.""",
    ),
    (
        "doc_046",
        """FAQ: Can I request an early check-in?
Early check-in requests are accommodated based on availability. We recommend calling the
hotel the day before arrival to enquire. An additional charge may apply for check-in before
08:00.""",
    ),
    (
        "doc_047",
        """FAQ: Does the hotel have a restaurant?
Our on-site restaurant is open for breakfast (06:30–10:30), lunch (12:00–14:30), and dinner
(18:00–22:00). A café and bar in the lobby serve light snacks and beverages throughout the
day until midnight.""",
    ),
    (
        "doc_048",
        """FAQ: Is the gym open 24 hours?
Yes, the fitness centre is accessible to all registered guests around the clock. A key card
is required for after-hours entry. Please note that gym equipment maintenance takes place
every Tuesday from 01:00 to 03:00.""",
    ),
    (
        "doc_049",
        """FAQ: How do I connect to Wi-Fi?
Select the network named "HotelGuest" on your device. Enter the password provided on your
key card envelope. If you experience connectivity issues, contact the front desk at any time
and our IT support team will assist you.""",
    ),
    (
        "doc_050",
        """FAQ: What is the late check-out fee?
Late check-out until 14:00 is complimentary when available. Staying between 14:00 and 18:00
incurs a charge of 50% of the nightly rate. Any checkout after 18:00 is billed at the full
nightly room rate.""",
    ),
]


def generate_documents(output_dir: str = None) -> None:
    """
    Write all 50 hotel documents to *output_dir*.

    Args:
        output_dir: Target directory.  Defaults to <repo_root>/data/docs/.
    """
    if output_dir is None:
        # Resolve relative to this file so the script works from any cwd.
        repo_root = pathlib.Path(__file__).resolve().parent.parent
        output_dir = repo_root / "data" / "docs"

    output_path = pathlib.Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    for doc_id, content in DOCUMENTS:
        file_path = output_path / f"{doc_id}.txt"
        file_path.write_text(content.strip(), encoding="utf-8")
        print(f"  Written: {file_path.name}")

    print(f"\nDone. {len(DOCUMENTS)} documents written to: {output_path}")


if __name__ == "__main__":
    generate_documents()
