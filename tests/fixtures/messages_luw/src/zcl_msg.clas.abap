CLASS zcl_msg DEFINITION PUBLIC.
  PUBLIC SECTION.
    METHODS constructor
      IMPORTING
        iv_x TYPE i
        io_msg TYPE REF TO zif_msg.
    METHODS run
      EXPORTING
        ev_y TYPE i
        et_messages TYPE bapiret2_t.
ENDCLASS.
CLASS zcl_msg IMPLEMENTATION.
  METHOD run.
    IF lv_x IS INITIAL.
      RETURN.
    ENDIF.
    LOOP AT lt ASSIGNING FIELD-SYMBOL(<l>).
      CHECK <l> IS NOT INITIAL.
    ENDLOOP.
    MESSAGE e001(zx) WITH lv_a INTO DATA(lv_m).
    MESSAGE w001(zx) WITH lv_a lv_b INTO lv_m.
    MESSAGE e002(zx) WITH lv_a INTO lv_m.
    MESSAGE e009(zx) INTO lv_m.
    MESSAGE ID 'ZX' TYPE 'E' NUMBER lv_no INTO lv_m.
    et_messages = _mo_msg->get( ).
  ENDMETHOD.
  METHOD fine.
    IF lv_x IS INITIAL.
      et_messages = _mo_msg->get( ).
      RETURN.
    ENDIF.
    et_messages = _mo_msg->get( ).
  ENDMETHOD.
  METHOD checked.
    CHECK lv_x IS NOT INITIAL.
    et_messages = _mo_msg->get( ).
  ENDMETHOD.
ENDCLASS.
