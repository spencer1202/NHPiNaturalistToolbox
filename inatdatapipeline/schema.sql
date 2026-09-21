-- Make sure the database is enforcing foreign key relationships
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS stats (
    stat_key    text    PRIMARY KEY,
    stat_value  text
);

-- Taxa tables
CREATE TABLE IF NOT EXISTS parent_taxa (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_egt_id   int     UNIQUE NOT NULL,
    parent_sci_name text
);
INSERT OR IGNORE INTO gpkg_contents (table_name, data_type, identifier)
VALUES ('parent_taxa', 'attributes', 'parent_taxa');

CREATE TABLE IF NOT EXISTS genera (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    genus_egt_id    int     UNIQUE NOT NULL,
    genus_sci_name  text
);
INSERT OR IGNORE INTO gpkg_contents (table_name, data_type, identifier)
VALUES ('genera', 'attributes', 'genera');

CREATE TABLE IF NOT EXISTS tracking_taxa (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    est_id                int     UNIQUE NOT NULL,
    egt_id                int     UNIQUE NOT NULL,
    sci_name              text    NOT NULL,
    global_sci_name       text    NOT NULL,
    override_name         text,
    classification_level  text    NOT NULL,
    is_described          boolean CHECK (is_described IN (NULL, true, false)) NOT NULL,
    parent_egt_id         int     REFERENCES parent_taxa(parent_egt_id) ON DELETE CASCADE,
    element_type          text,
    common_name           text,
    family                text,
    genus_egt_id          int     NOT NULL REFERENCES genera(genus_egt_id) ON DELETE CASCADE,
    author                text,
    egt_uid               int,
    srank                 text,
    track_status          text,
    explorer              text,
    elcode                text,
    growth_habit          text,
    duration              text
);
INSERT OR IGNORE INTO gpkg_contents (table_name, data_type, identifier)
VALUES ('tracking_taxa', 'attributes', 'tracking_taxa');

CREATE TABLE IF NOT EXISTS inat_taxa (
    id                    INTEGER     PRIMARY KEY AUTOINCREMENT,
    taxon_id              int         UNIQUE NOT NULL,
    inat_name             text,
    date_updated          text
);
INSERT OR IGNORE INTO gpkg_contents (table_name, data_type, identifier)
VALUES ('inat_taxa', 'attributes', 'inat_taxa');

CREATE TABLE IF NOT EXISTS tracking_rel (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    taxon_id              int     NOT NULL REFERENCES inat_taxa(taxon_id) ON DELETE CASCADE,
    est_id                int     UNIQUE REFERENCES tracking_taxa(est_id) ON DELETE CASCADE,
    parent_egt_id         int     UNIQUE REFERENCES parent_taxa(parent_egt_id) ON DELETE CASCADE,
    genus_egt_id          int     UNIQUE REFERENCES genera(genus_egt_id) ON DELETE CASCADE
);
INSERT OR IGNORE INTO gpkg_contents (table_name, data_type, identifier)
VALUES ('tracking_rel', 'attributes', 'tracking_rel');

DROP TRIGGER IF EXISTS trg_inat_cascade_delete;
CREATE TRIGGER trg_inat_cascade_delete
AFTER DELETE ON inat_taxa
FOR EACH ROW
BEGIN
    DELETE FROM tracking_rel WHERE taxon_id = OLD.taxon_id;
END;

DROP TRIGGER IF EXISTS trg_tracking_cascade_delete;
CREATE TRIGGER trg_tracking_cascade_delete
AFTER DELETE ON tracking_taxa
FOR EACH ROW
BEGIN
    -- est_id-linked tracking_rel rows are removed automatically via
    -- ON DELETE CASCADE on tracking_rel.est_id -> tracking_taxa.est_id
    DELETE FROM tracking_rel
    WHERE (
        -- Parent-level fallback: only delete if no remaining tracking_taxa
        -- row under this parent still lacks its own est-specific rel row
        OLD.parent_egt_id IS NOT NULL
        AND parent_egt_id = OLD.parent_egt_id
        AND NOT EXISTS (
            SELECT 1 FROM tracking_taxa
            WHERE parent_egt_id = OLD.parent_egt_id
            AND est_id NOT IN (SELECT est_id FROM tracking_rel WHERE est_id IS NOT NULL)
        )
    )
    OR (
        -- Genus-level fallback: same idea, one level up
        genus_egt_id = OLD.genus_egt_id
        AND NOT EXISTS (
            SELECT 1 FROM tracking_taxa
            WHERE genus_egt_id = OLD.genus_egt_id
            AND est_id NOT IN (SELECT est_id FROM tracking_rel WHERE est_id IS NOT NULL)
        )
    );
END;

DROP TRIGGER IF EXISTS trg_tracking_rel_cascade_delete;
CREATE TRIGGER trg_tracking_rel_cascade_delete
AFTER DELETE ON tracking_rel
FOR EACH ROW
BEGIN
    -- A tracking_rel row disappearing (directly, via cascade from a
    -- tracking_taxa delete, or via the fallback cleanup above) means
    -- nothing vouches for that inat mapping anymore, UNLESS some other
    -- tracking_rel row still points at the same taxon.
    DELETE FROM inat_taxa
    WHERE taxon_id = OLD.taxon_id
    AND NOT EXISTS (
        SELECT 1 FROM tracking_rel WHERE tracking_rel.taxon_id = OLD.taxon_id
    );
END;

-- Observation tables
CREATE TABLE IF NOT EXISTS users (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id               int     UNIQUE NOT NULL,
    login                 text,
    name                  text
);
INSERT OR IGNORE INTO gpkg_contents (table_name, data_type, identifier)
VALUES ('users', 'attributes', 'users');


CREATE TABLE IF NOT EXISTS observations (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_id              int     UNIQUE NOT NULL,
    uuid                        text    NOT NULL,
    observer_id                 int     NOT NULL REFERENCES users(user_id),
    taxon_id                    int     NOT NULL REFERENCES inat_taxa(taxon_id),
    license                     text,
    latitude                    float,
    longitude                   float,
    latitude_private            float,
    longitude_private           float,
    coordinate_precision        float,
    coordinate_precision_public float,
    observed_on                 text,
    observed_on_string          text,
    created_at                  text,
    updated_at                  text,
    quality_grade               text,
    url                         text,
    description                 text,
    id_agreements               int,
    id_disagreements            int,
    place_guess                 text,
    place_guess_private         text,
    captive_cultivated          boolean CHECK (captive_cultivated IN (NULL, true, false)),
    obscured                    boolean CHECK (obscured IN (NULL, true, false)),
    has_photo                   boolean CHECK (has_photo IN (NULL, true, false)),
    has_recording               boolean CHECK (has_recording IN (NULL, true, false))
);
INSERT OR IGNORE INTO gpkg_contents (table_name, data_type, identifier)
VALUES ('observations', 'attributes', 'observations');

CREATE TABLE IF NOT EXISTS identifications (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    identification_id     int     UNIQUE NOT NULL,
    observation_id        int     NOT NULL REFERENCES observations(observation_id),
    user_id               int     NOT NULL REFERENCES users(user_id),
    taxon_id              int     NOT NULL REFERENCES inat_taxa(taxon_id),
    created_at            text
);
INSERT OR IGNORE INTO gpkg_contents (table_name, data_type, identifier)
VALUES ('identifications', 'attributes', 'identifications');

CREATE TABLE IF NOT EXISTS annotations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    annotation_id       int     NOT NULL,
    value_id            int     NOT NULL,
    observation_id      int     NOT NULL,
    user_id             int     NOT NULL,
    vote_score          int     NOT NULL,
    UNIQUE(annotation_id, value_id, observation_id),
    FOREIGN KEY(annotation_id, value_id) 
        REFERENCES annotation_values(annotation_id, value_id)
);
INSERT OR IGNORE INTO gpkg_contents (table_name, data_type, identifier)
VALUES ('annotations', 'attributes', 'annotations');


-- Annotations tables
CREATE TABLE IF NOT EXISTS annotation_options (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    annotation_id       int     UNIQUE NOT NULL,
    label               text    NOT NULL
);
INSERT OR IGNORE INTO gpkg_contents (table_name, data_type, identifier)
VALUES ('annotation_options', 'attributes', 'annotation_options');

CREATE TABLE IF NOT EXISTS annotation_values (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    annotation_id       int     NOT NULL REFERENCES annotations(annotation_id),
    value_id            int     NOT NULL,
    label               text    NOT NULL,
    UNIQUE(value_id, annotation_id)
);
INSERT OR IGNORE INTO gpkg_contents (table_name, data_type, identifier)
VALUES ('annotation_values', 'attributes', 'annotation_values');


-- Other info tables
CREATE TABLE IF NOT EXISTS experts (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id               int     UNIQUE NOT NULL,
    expertise             text
);
INSERT OR IGNORE INTO gpkg_contents (table_name, data_type, identifier)
VALUES ('experts', 'attributes', 'experts');

CREATE TABLE IF NOT EXISTS project_members (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     int     UNIQUE NOT NULL
);
INSERT OR IGNORE INTO gpkg_contents (table_name, data_type, identifier)
VALUES ('project_members', 'attributes', 'project_members');


-- Views
DROP VIEW IF EXISTS mappings;
CREATE VIEW mappings(
    est_id,
    egt_id,
    elcode,
    sci_name,
    override_name,
    parent_egt_id,
    parent_sci_name,
    genus_egt_id,
    genus_sci_name,
    common_name,
    classification_level,
    is_described,
    match_element_id,
    taxon_id,
    inat_name,
    date_updated,
    match_type
)
AS SELECT
    tt.est_id,
    tt.egt_id,
    tt.elcode,
    tt.sci_name,
    tt.override_name,
    tr.parent_egt_id,
    pt.parent_sci_name,
    tr.genus_egt_id,
    gt.genus_sci_name,
    tt.common_name,
    tt.classification_level,
    tt.is_described,
    COALESCE(tr.est_id, tr.parent_egt_id, tr.genus_egt_id) AS match_element_id,
    tr.taxon_id,
    it.inat_name,
    it.date_updated,
    CASE
        WHEN tr.genus_egt_id IS NOT NULL  THEN 'genus'
        WHEN tr.parent_egt_id IS NOT NULL THEN 'parent'
        WHEN tt.override_name IS NOT NULL THEN 'override'
        ELSE 'exact'
    END AS match_type
FROM inat_taxa it
JOIN tracking_rel tr ON it.taxon_id=tr.taxon_id 
LEFT JOIN parent_taxa pt ON tr.parent_egt_id=pt.parent_egt_id 
LEFT JOIN genera gt ON tr.genus_egt_id=gt.genus_egt_id
LEFT JOIN tracking_taxa tt ON (
    tr.est_id=tt.est_id
    OR (
        pt.parent_egt_id=tt.parent_egt_id 
        AND tt.est_id NOT IN (SELECT est_id FROM tracking_rel WHERE est_id IS NOT NULL)
    )
    OR (
        gt.genus_egt_id=tt.genus_egt_id
        AND tt.est_id NOT IN (SELECT est_id FROM tracking_rel WHERE est_id IS NOT NULL)
    )
);
INSERT OR IGNORE INTO gpkg_contents (table_name, data_type, identifier)
VALUES ('mappings', 'attributes', 'mappings');


DROP VIEW IF EXISTS expert_identifications;
CREATE VIEW IF NOT EXISTS expert_identifications (
    identification_id,
    observation_id,
    user_id,
    login,
    name,
    taxon_id,
    created_at,
    est_id,
    elcode,
    expertise
)
AS SELECT
    id.identification_id,
    id.observation_id,
    id.user_id,
    us.login,
    us.name,
    id.taxon_id,
    id.created_at,
    tr.est_id,
    tr.elcode,
    ex.expertise
FROM identifications AS id
LEFT JOIN tracking_rel 
    ON id.taxon_id = tracking_rel.taxon_id
LEFT JOIN tracking_taxa AS tr 
    ON tracking_rel.est_id = tr.est_id
JOIN experts AS ex 
    ON id.user_id = ex.user_id
JOIN users AS us
    ON id.user_id = us.user_id
;
INSERT OR IGNORE INTO gpkg_contents (table_name, data_type, identifier)
VALUES ('expert_identifications', 'attributes', 'expert_identifications');

DROP VIEW IF EXISTS annotations_with_labels;
CREATE VIEW IF NOT EXISTS annotations_with_labels (
    observation_id,
    annotation_id,
    value_id,
    annotation_label,
    value_label,
    user_id,
    vote_score
)
AS SELECT
    ann.observation_id,
    ann.annotation_id,
    ann.value_id,
    ao.label,
    av.label,
    ann.user_id,
    ann.vote_score
FROM annotations ann
JOIN annotation_values av
    ON ann.value_id = av.value_id
JOIN annotation_options ao
    ON ann.annotation_id = ao.annotation_id
;

-- TODO fix
DROP VIEW IF EXISTS full_observations;
CREATE VIEW IF NOT EXISTS full_observations
AS SELECT
    obs.observation_id,
    obs.uuid,
    obs.observer_id,
    us.name,
    us.login,
    obs.taxon_id,
    obs.license,
    obs.latitude,
    obs.longitude,
    obs.latitude_private,
    obs.longitude_private,
    obs.coordinate_precision,
    obs.coordinate_precision_public,
    obs.observed_on,
    obs.observed_on_string,
    obs.created_at,
    obs.updated_at,
    obs.quality_grade,
    obs.url,
    obs.description,
    obs.id_agreements,
    obs.id_disagreements,
    obs.place_guess,
    obs.place_guess_private,
    obs.captive_cultivated,
    obs.obscured,
    obs.has_photo,
    obs.has_recording,
    tt.est_id,
    tt.egt_id,
    tt.sci_name,
    tt.global_sci_name,
    tt.override_name,
    tt.classification_level,
    tt.is_described,
    tt.parent_egt_id,
    pt.parent_sci_name,
    tt.element_type,
    tt.common_name,
    tt.family,
    tt.genus_egt_id,
    ge.genus_sci_name,
    tt.author,
    tt.egt_uid,
    tt.srank,
    tt.track_status,
    tt.explorer,
    tt.elcode,
    tt.growth_habit,
    tt.duration
FROM observations obs
JOIN users us
    ON obs.observer_id = us.user_id
LEFT JOIN tracking_rel tr
    ON obs.taxon_id = tr.taxon_id
JOIN tracking_taxa tt
    ON tt.est_id = tr.est_id
LEFT JOIN parent_taxa pt
    ON tt.parent_egt_id = pt.parent_egt_id
LEFT JOIN genera ge
    ON tt.genus_egt_id = ge.genus_egt_id
;
INSERT OR IGNORE INTO gpkg_contents (table_name, data_type, identifier)
VALUES ('full_observations', 'attributes', 'full_observations');