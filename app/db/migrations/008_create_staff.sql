-- NBA Staff ID card table
CREATE TABLE IF NOT EXISTS staff (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name      TEXT        NOT NULL,
    department     TEXT        NOT NULL,
    photo_url      TEXT,
    signature_url  TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed from Google Form responses (passport photos / signatures to be uploaded manually)
INSERT INTO staff (full_name, department) VALUES
    ('Peace Ajuri Obe',          'Account'),
    ('Femi Adegunloye',          'Membership and Bar Services'),
    ('Mophet Bamaiyi Joseph',    'I.C.T'),
    ('Ioryue Luter Luther',      'Admin & Human Resource'),
    ('Levi Enyojo Blessing',     'Administration and Human Resources'),
    ('Timothy Sunday',           'Protocol and Special Duties/Protocol'),
    ('Jimwa Comfort Nzuta',      'Pro-Bono'),
    ('Halimat Yetunde Yusuph',   'Pro-Bono Centre'),
    ('Glory Pwanidi Lawrence',   'Membership & Bar Services Department'),
    ('Obed Zakka',               'Admin'),
    ('Henry Enya Abung',         'Membership and Bar Services'),
    ('Ezekiel Adauji David',     'Bar Services'),
    ('Abhulimen Victor',         'Protocol'),
    ('Amoo Omowumi Seun',        'Admin - Office of the General Secretary'),
    ('Tobin-Dibiah Emmanuella',  'Admin - Office of the General Secretary'),
    ('Jerry Bawa Stephen',       'Protocol/Maintenance'),
    ('Felix Mutuah',             'Membership and Bar Services Department'),
    ('Sime Dikia David-West',    'Membership and Bar Service'),
    ('Sarah Omega Ajijola',      'NBA Institute of Continuing Legal Education'),
    ('Adewale Adebayo Ali',      'Bar Services'),
    ('Peter Adirahu Onah',       'Protocol Officer'),
    ('Chioma Helen Onyeje',      'Programmes Department'),
    ('Monday Thomas Musa',       'Protocol Unit'),
    ('Joseph Bitrus Maidawa',    'Protocol Officer'),
    ('Ayodeji Olatokunbo Oni',   'Membership and Bar Services'),
    ('Philip Bulus',             'Administrative Officer'),
    ('Yomi Owolabi',             'Human Right Institute'),
    ('Kazeem Nasir',             'Director, Protocol and Special Duties'),
    ('Abubakar Jibo Abdullahi',  'I.T'),
    ('Grace Mlumun Igyo',        'Legal Regulatory and Compliance Department'),
    ('Salamatu Nyand Sidi',      'Administration and Human Resources'),
    ('Samson I. Ishaya',         'Protocol Department'),
    ('Mirabel Mosugu-Gabriel',   'Head, Human Rights Institute'),
    ('Timothy Samuel',           'Admin'),
    ('Folake Godwin-Peters',     'Administrative')
ON CONFLICT DO NOTHING;
