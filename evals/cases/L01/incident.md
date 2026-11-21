# Checkout API 5xx spike

Alert: checkout-api HTTP 5xx rate above 5% for 5 minutes.
Fired at 2026-03-14 14:07 UTC. The error rate started rising at 14:02 UTC
and was still high when this page was opened.

What customers see: POST /v1/checkout returns HTTP 500, and the site says
"payment could not be completed". GET /health on checkout-api is still 200.

Catalog search and the checkout database both look up from the outside.
No other service has an open page.
