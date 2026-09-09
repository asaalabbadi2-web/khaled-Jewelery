# SAR_USD_PEG: Saudi Riyal / USD peg in effect since 1986.
# Political rate, not a market rate — intentionally a named constant, not a bare literal.
# Lives here so the 2b reasonableness guard in D-1 has one import, not seven.
SAR_USD_PEG: float = 3.75

# Standard troy ounce → gram conversion (fixed by definition).
TROY_OZ_TO_GRAMS: float = 31.1035
