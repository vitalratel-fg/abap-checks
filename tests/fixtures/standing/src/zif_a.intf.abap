INTERFACE zif_a PUBLIC.
  TYPES mty_x TYPE i.
  TYPES bad_type TYPE i.
  TYPES:
    BEGIN OF mty_s,
      comp TYPE i,
    END OF mty_s.
  CONSTANTS mc_used TYPE i VALUE 1.
  CONSTANTS mc_dead TYPE i VALUE 2.
  METHODS run RAISING zcx_a.
  METHODS quiet.
ENDINTERFACE.
