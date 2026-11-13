CLASS zcl_collect DEFINITION PUBLIC.
  PUBLIC SECTION.
    CONSTANTS:
      BEGIN OF mc_not_found,
        msgid TYPE symsgid VALUE 'ZX',
        msgno TYPE symsgno VALUE '002',
        attr1 TYPE scx_attrname VALUE '',
      END OF mc_not_found,
      BEGIN OF mc_elsewhere,
        msgid TYPE symsgid VALUE 'SY',
        msgno TYPE symsgno VALUE '499',
      END OF mc_elsewhere.
    METHODS constructor IMPORTING io_msg TYPE REF TO zif_msg.
ENDCLASS.
CLASS zcl_collect IMPLEMENTATION.
ENDCLASS.
