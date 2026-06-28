import sys
import os
sys.path.insert(0, str(Path(__file__).parent))
from sender import send_email

to_email = "info@wickerparkfitness.com"
subject = "Cost?"
business_id = 97

body = """Hi Wicker Park Fitness Team,

Apologies for the delay! I wanted to take the time to really look under the hood of your current Squarespace site and ClubReady system to give you an accurate quote.

As the only 24/7 gym in Wicker Park, you have a massive advantage, but your current site is holding you back. Beyond fixing the slow 45/100 mobile speed, I found three low-hanging opportunities to drastically increase your online sign-ups:
*   Highlighting Checkouts: Your ClubReady links are currently tucked away. We need to bring them front-and-center.
*   The $150 PT Promo: Instead of forcing clients to email you to claim this, we can add a frictionless "click-to-buy" button.
*   Free Workout Capture: We can add a simple pop-up for the free workout offer to automatically capture leads, even if they don't show up.

I keep my pricing simple with two one-time flat fees:

Option 1: The Core Redesign ($1,500)
We completely visually remake your website (like the demo I sent) and optimize it for Chicago SEO. We keep your existing ClubReady links but integrate them cleanly so they convert better on mobile.

Option 2: The Automation Setup ($2,000)
Everything in Option 1, plus we build a fully custom, branded checkout directly on your website so users don't have to leave the page. We also set up the lead-capture forms and the digital checkout for the PT promo.

Optional: Hands-Free Site Management ($100/mo)
If you'd prefer to be completely hands-off, I offer an unlimited site management retainer. Whenever you want to swap out gym photos, change class schedules, or put up a new holiday promo, you just shoot me an email and I will personally build and update the site for you so you never have to touch the code.

Which route aligns best with your vision right now?

Best,
Chandan"""

try:
    success = send_email(
        to_email=to_email,
        subject=subject,
        body=body,
        business_id=business_id
    )
    if success:
        print("Email sent successfully!")
    else:
        print("Failed to send email.")
except Exception as e:
    print("Error:", e)
