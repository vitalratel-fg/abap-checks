@AccessControl.authorizationCheck: #NOT_REQUIRED
define view entity zi_misc as select from acdoca as a
  inner many to one join zv_old_stuff as v on v.k = a.k
  inner many to one join zt_one as c on c.k = '1'
{
  key a.k as K,
  key abs(a.amt) as Amt,
  a.amt1 as amt1,
  a.amt2 as amt2,
  rank() over (order by a.k) as Rnk
}
where a.x = '1' and a.y = '2' or a.z = '3'
  and (a.q <> '1' or a.q <> '2')
