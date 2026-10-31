# Polaris display panel contract

This component records the Polaris DSI panel candidates found in the stock
DTB/vendor evidence: JDI NT35596S, JDI R63452, EBBG FT8716 and EBBG FT8719.
It validates only board identity, the presence of `dsi-display` candidate
nodes, and the panel kind parsed from each node's `label`.

It does **not** publish a resolution. The reference DTB timing nodes disagree
on panel height for these four candidates (1080x1920 for the JDI R63452 build,
1080x2160 for JDI NT35596S and EBBG FT8716, 1080x2246 for EBBG FT8719), so a
single "1080x2160" claim would have been an overstatement. The service
therefore publishes `polaris-display-resolution="unresolved"` with
`polaris-display-geometry-confirmed=false` and
`polaris-display-dsi-lanes-confirmed=false`, and the plan stops at
`PolarisDisplayPanelReasonGeometryUnconfirmed`. `polaris-display-panel-selected`
stays `false` because more than one candidate label can be present and the DT
does not say which panel this unit has.

It never selects a panel, writes DSI commands, controls a
regulator/backlight, maps MDSS, loads firmware, creates DMA, or enables GPU
composition. It is therefore a resource contract, not a working display
driver, and remains gated behind `polaris-display-probe=1`.
