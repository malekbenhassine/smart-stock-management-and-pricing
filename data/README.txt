Fake dataset pour projet Stock/Pricing (CSV + config JSON)
Contenu:
- users.csv: comptes + rôles + flags (activation, must_set_password, locked_until)
- auth_events.csv: tentatives login + lockout
- products.csv: produits + prix/couts + seuils + stock courant
- suppliers.csv: fournisseurs
- product_suppliers.csv: liens produit-fournisseur + lead time + cost
- purchase_orders.csv + purchase_order_lines.csv: commandes fournisseurs
- stock_movements.csv: entrées/sorties avec références (PO, SALE)
- sales.csv: ventes (timestamp, qty, unit_price)
- competitors.csv + competitor_prices.csv: veille concurrentielle + statuts collecte
- promotions.csv: promos + workflow (pending/approved/active/etc.)
- price_recommendations.csv: recommandations tarifaires + décisions
- alerts.csv: alertes (stock/prix/système) + is_read/read_at
- inventory_counts.csv: inventaire (stock système vs physique) + écarts
