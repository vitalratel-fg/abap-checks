@AccessControl.authorizationCheck: #NOT_REQUIRED
define view entity zc_bare as select from zt_one as o
  association of many to one zi_twice as _Tw on _Tw.K = o.k and _Tw.G = o.g
{
  key o.k as Key,
  _Tw.F as plant,
  _Tw
}
