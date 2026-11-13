CLASS zcl_user DEFINITION PUBLIC FINAL.
  PUBLIC SECTION.
    METHODS constructor.
    METHODS go.
    METHODS guarded RAISING zcx_a.
    TYPES ty_public TYPE i.
    TYPES mty_public TYPE i.
  PROTECTED SECTION.
    TYPES mty_wrong TYPE i.
    TYPES _mty_fine TYPE i.
  PRIVATE SECTION.
    DATA _mo_a TYPE REF TO zif_a.
    DATA _mo_o TYPE REF TO zif_o.
    DATA _mv_read TYPE i.
    DATA _mv_lost TYPE i.
    CONSTANTS:
      BEGIN OF _mc_kind,
        used TYPE c LENGTH 1 VALUE 'U',
        dead TYPE c LENGTH 1 VALUE 'D',
      END OF _mc_kind.
    METHODS _used.
    METHODS _dead.
    METHODS _on_event FOR EVENT changed OF zif_a.
    METHODS _test FOR TESTING.
    METHODS setup.
    METHODS _caught.
ENDCLASS.

CLASS zcl_user IMPLEMENTATION.
  METHOD constructor.
    _mv_read = 1.
    _mv_lost = 2.
    _used( ).
    DATA(lv) = zif_a=>mc_used.
  ENDMETHOD.
  METHOD go.
    _mo_o->typed( ).
    _mo_o->zif_o~qualified( ).
    DATA(lo_c) = NEW zcl_impl_o( ).
    lo_c->via_class( ).
    lo_unknown->by_name( ).
    CALL BADI lo_badi->badi_meth.
    _mo_a->run( ).
    cl_demo=>show( _mv_read ).
    DATA(lv_k) = _mc_kind-used.
    DATA(lv_t) = zif_a=>mty_x.
    DATA(lv_m) = zif_a=>missing.
    DATA(lv_l) = zcl_user=>lv_local.
    DATA(lv_s) = zif_a=>comp.
    LOOP AT lt_rows INTO DATA(ls_row).
    ENDLOOP.
    NEW zcl_missing( ).
    DATA lo_n TYPE REF TO zcl_not_there.
  ENDMETHOD.
  METHOD guarded.
    _mo_a->run( ).
  ENDMETHOD.
  METHOD _caught.
    TRY.
        _mo_a->run( ).
      CATCH zcx_a.
    ENDTRY.
  ENDMETHOD.
  METHOD _used.
    DATA lv_local TYPE i.
  ENDMETHOD.
  METHOD _dead.
  ENDMETHOD.
  METHOD _on_event.
  ENDMETHOD.
  METHOD _test.
  ENDMETHOD.
  METHOD setup.
  ENDMETHOD.
ENDCLASS.
