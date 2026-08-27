select 
    to_char(est.element_subnational_id) "name", 
    sname.scientific_name||' : '|| est.s_primary_common_name as "label", 
    sname.scientific_name "sname", sname.author_name as "author", 
    est.s_primary_common_name "scomname", 
    est.s_rank "s_rank", 
    D_EO_TRACK_STATUS.eo_track_status_desc "eo_track_status_desc", 
    'https://explorer.natureserve.org/Taxon/ELEMENT_GLOBAL.'||egt.element_global_ou_uid||'.'||egt.element_global_seq_uid as "explorer", 
    'ELEMENT_GLOBAL.'||egt.element_global_ou_uid||'.'||egt.element_global_seq_uid as "egt_uid", 
    hcu_f.higher_class_unit_name AS "family", 
    egt.elcode_bcd as elcode_bcd, 
    nc.name_category_desc,
    delimlist(
        'SELECT dgh.growth_habit_desc' 
        || ' FROM D_GROWTH_HABIT dgh, PLANT_CAG_GROWTH_HABIT gh' 
        || ' WHERE gh.d_growth_habit_id = dgh.d_growth_habit_id (+) and gh.element_global_id (+) = ' 
        || egt.element_global_id
    ) "growth_habit",
    case when egt.elcode_bcd like 'A%' or egt.elcode_bcd like 'I%' then 'Animal'
        when egt.elcode_bcd like 'P%' or egt.elcode_bcd like 'N%' then 'Plant'
        when egt.elcode_bcd like 'C%' or egt.elcode_bcd like 'G%' then 'Community'
    end "element_type",
    d_duration.duration_desc "duration"
from 
    element_subnational est, 
    scientific_name sname, 
    element_global egt, 
    element_national ent, 
    D_EO_TRACK_STATUS, 
    higher_class_unit hcu, 
    higher_class_unit hcu_f, 
    D_NAME_CATEGORY nc, 
    d_duration, 
    plant_cag_duration pcd, 
    plant_cag
where est.sname_id = sname.scientific_name_id 
    and est.element_national_id=ent.element_national_id 
    and ent.element_global_id=egt.element_global_id 
    and egt.higher_class_unit_id = hcu.higher_class_unit_id(+)
    and hcu.parent_unit_id = hcu_f.higher_class_unit_id(+)
    and est.d_eo_track_status_id = D_EO_TRACK_STATUS.d_eo_track_status_id (+)
    and sname.D_NAME_CATEGORY_id = nc.D_NAME_CATEGORY_id (+)
    and egt.element_global_id = plant_cag.element_global_id (+)
    and plant_cag.element_global_id = pcd.element_global_id (+)
    and pcd.d_duration_id = d_duration.d_duration_id (+)
    and D_EO_TRACK_STATUS.eo_track_status_desc = 'Track all extant and selected historical EOs'
order by scientific_name