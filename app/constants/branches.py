# Official NBA branch list — source from NBA secretariat for full list.
# Used for validation of the `branch` field on member profiles.

NBA_BRANCHES: list[str] = [
    "Abuja",
    "Aba",
    "Abeokuta",
    "Ado-Ekiti",
    "Akure",
    "Asaba",
    "Awka",
    "Bauchi",
    "Benin City",
    "Calabar",
    "Enugu",
    "Ibadan",
    "Ilorin",
    "Jos",
    "Kaduna",
    "Kano",
    "Lagos",
    "Maiduguri",
    "Makurdi",
    "Nnewi",
    "Ondo",
    "Onitsha",
    "Osogbo",
    "Owerri",
    "Port Harcourt",
    "Sokoto",
    "Umuahia",
    "Uyo",
    "Warri",
    "Yola",
]

NBA_BRANCHES_SET: set[str] = set(NBA_BRANCHES)
