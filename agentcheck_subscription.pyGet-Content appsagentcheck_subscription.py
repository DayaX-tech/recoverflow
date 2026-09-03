[1mdiff --git a/apps/storefront/index.html b/apps/storefront/index.html[m
[1mindex 7ff4b01..486e5de 100644[m
[1m--- a/apps/storefront/index.html[m
[1m+++ b/apps/storefront/index.html[m
[36m@@ -778,7 +778,7 @@[m
                 var res = await fetch(API + '/create-order', {[m
                     method: 'POST',[m
                     headers: { 'Content-Type': 'application/json' },[m
[31m-                    body: JSON.stringify({ plan: plan, phone: customerPhone })[m
[32m+[m[32m                    body: JSON.stringify({ plan: plan, phone: customerPhone, purchase_type: "subscription" })[m
                 });[m
                 if (!res.ok) throw new Error('order failed: ' + res.status);[m
                 var data = await res.json();[m
