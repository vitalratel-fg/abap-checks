@AccessControl.authorizationCheck: #NOT_REQUIRED
define view entity zi_toone as select from zt_one as o
  left outer to one join zt_two as t on t.a = o.k
  left outer to one join zt_unknown as u on u.k = o.k
  association of many to one zi_twice as _Twice on _Twice.K = o.k
{
  key o.k as K,
  o.companycode as companycode,
  _Twice
}
