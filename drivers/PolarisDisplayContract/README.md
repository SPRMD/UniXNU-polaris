# Polaris display panel contract

This component records the Polaris DSI panel candidates found in the stock
DTB/vendor evidence: JDI NT35596S, JDI R63452, EBBG FT8716 and EBBG FT8719.
It validates only board identity and static 1080x2160/4-lane geometry. It never
selects a panel, writes DSI commands, controls a regulator/backlight, maps MDSS,
loads firmware, creates DMA, or enables GPU composition. It is therefore a
resource contract, not a working display driver, and remains gated behind
`polaris-display-probe=1`.
