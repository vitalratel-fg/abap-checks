CLASS zcl_b_service DEFINITION PUBLIC.
  PUBLIC SECTION.
    METHODS later IMPORTING io_luw TYPE REF TO zif_luw.
    METHODS build.
ENDCLASS.
CLASS zcl_b_service IMPLEMENTATION.
  METHOD build.
    DATA(lo) = NEW zcl_repo( ).
  ENDMETHOD.
ENDCLASS.
