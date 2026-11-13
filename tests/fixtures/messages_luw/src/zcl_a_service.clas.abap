CLASS zcl_a_service DEFINITION PUBLIC.
  PUBLIC SECTION.
    METHODS constructor IMPORTING io_luw TYPE REF TO zif_luw.
    METHODS build.
ENDCLASS.
CLASS zcl_a_service IMPLEMENTATION.
  METHOD constructor.
  ENDMETHOD.
  METHOD build.
    DATA(lo1) = NEW zcl_repo( io_luw = _mo_luw ).
    DATA(lo2) = NEW zcl_store( io_luw = _mo_other ).
    DATA(lo3) = NEW zcl_repo( ).
  ENDMETHOD.
ENDCLASS.
