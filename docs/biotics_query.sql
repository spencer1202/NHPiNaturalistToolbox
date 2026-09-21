SELECT
    est.element_subnational_id AS "est_id",
    egt.element_global_id AS "egt_id",
    sname.scientific_name AS "sci_name",
    sname_g.scientific_name AS "global_sci_name",
    dcl.classification_level_name AS "classification_level",
    egt_p.element_global_id AS "parent_egt_id",
    sname_p.scientific_name AS "parent_sci_name",
    sname.author_name AS "author",
    est.s_primary_common_name AS "scomname",
    hcu.higher_class_unit_name AS "genus",
    hcu.higher_class_unit_id AS "genus_egt_id",
    hcu_f.higher_class_unit_name AS "family",
    egt.elcode_bcd AS "elcode_bcd",
    est.s_rank AS "s_rank",
    deots.eo_track_status_desc AS "eo_track_status_desc",
    'https://explorer.natureserve.org/Taxon/ELEMENT_GLOBAL.'||egt.element_global_ou_uid||'.'||egt.element_global_seq_uid AS "explorer",
    'ELEMENT_GLOBAL.'||egt.element_global_ou_uid||'.'||egt.element_global_seq_uid AS "egt_uid",
    nc.name_category_desc AS "name_category_desc",
    delimlist(
        'SELECT dgh.growth_habit_desc' 
        || ' FROM D_GROWTH_HABIT dgh, PLANT_CAG_GROWTH_HABIT gh' 
        || ' WHERE gh.d_growth_habit_id = dgh.d_growth_habit_id (+) and gh.element_global_id (+) = ' 
        || egt.element_global_id
    ) AS "growth_habit",
    case when egt.elcode_bcd like 'A%' or egt.elcode_bcd like 'I%' then 'Animal'
        when egt.elcode_bcd like 'P%' or egt.elcode_bcd like 'N%' then 'Plant'
        when egt.elcode_bcd like 'C%' or egt.elcode_bcd like 'G%' then 'Community'
    end AS "element_type",
    delimlist(
        'SELECT dd.duration_desc'
        || ' FROM d_duration dd, plant_cag_duration pcd'
        || ' WHERE dd.d_duration_id = pcd.d_duration_id (+) and pcd.element_global_id = '
        || egt.element_global_id  
    ) AS "duration"
FROM element_subnational est
JOIN scientific_name sname
    ON est.sname_id = sname.scientific_name_id
JOIN element_national ent
    ON est.element_national_id=ent.element_national_id
JOIN element_global egt
    ON ent.element_global_id=egt.element_global_id
JOIN scientific_name sname_g
    ON egt.gname_id=sname_g.scientific_name_id
JOIN taxon_global txg
    ON  egt.element_global_id=txg.element_global_id
JOIN d_classification_level dcl
    ON sname.d_classification_level_id=dcl.d_classification_level_id
LEFT JOIN higher_class_unit hcu
    ON egt.higher_class_unit_id=hcu.higher_class_unit_id
LEFT JOIN higher_class_unit hcu_f
    ON hcu.parent_unit_id=hcu_f.higher_class_unit_id
LEFT JOIN d_eo_track_status deots
    ON est.d_eo_track_status_id=deots.d_eo_track_status_id
LEFT JOIN d_name_category nc
    ON sname.d_name_category_id=nc.d_name_category_id
LEFT JOIN plant_cag pc
    ON egt.element_global_id=pc.element_global_id
LEFT JOIN element_global egt_p
    ON txg.parent_species_id=egt_p.element_global_id
LEFT JOIN scientific_name sname_p
    ON egt_p.gname_id = sname_p.scientific_name_id
WHERE
    deots.eo_track_status_desc = 'Track all extant and selected historical EOs'
ORDER BY sname.scientific_name