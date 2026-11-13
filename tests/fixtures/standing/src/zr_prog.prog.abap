REPORT zr_prog.
CLASS lcl_app DEFINITION.
  PUBLIC SECTION.
    METHODS run.
    TYPES ty_loc TYPE i.
  PRIVATE SECTION.
    DATA _mv_only_set TYPE i.
ENDCLASS.
CLASS lcl_app IMPLEMENTATION.
  METHOD run.
    _mv_only_set = 3.
  ENDMETHOD.
ENDCLASS.
